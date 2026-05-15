"""Authenticates and wires up a third-party integration (e.g. Gmail, Slack)."""

import re
import os
import subprocess
import shutil
import webbrowser
import click
import yaml
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from alfard.integrations.catalogue import CATALOGUE, AUTH_APIKEY, AUTH_OAUTH

console = Console()

_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
_INTEGRATIONS_PATH = Path(__file__).parent.parent.parent / "config" / "integrations.yaml"


def _update_env(key: str, value: str) -> None:
    lines: list[str] = []
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text().splitlines()

    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    updated = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        lines.append(f"{key}={value}")

    _ENV_PATH.write_text("\n".join(lines) + "\n")


def _load_integrations() -> dict:
    if not _INTEGRATIONS_PATH.exists():
        return {"servers": []}
    raw = _INTEGRATIONS_PATH.read_text()
    data = yaml.safe_load(raw)
    if not data:
        return {"servers": []}
    return data


def _save_integrations(data: dict) -> None:
    _INTEGRATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _INTEGRATIONS_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _already_connected(name: str) -> bool:
    data = _load_integrations()
    return any(s["name"] == name for s in data.get("servers", []))


def _connect_apikey(name: str, integration: dict) -> bool:
    console.print(Panel(
        integration["description"],
        title=integration["display_name"],
        border_style="cyan",
    ))

    console.print("\n[bold]How to get your token:[/bold]")
    for line in integration["get_token_steps"].splitlines():
        console.print(line)

    url = integration.get("get_token_url", "")
    if url:
        console.print(f"\nOpening [bold cyan]{url}[/bold cyan]")
        webbrowser.open(url)

    token = Prompt.ask(
        f"\nPaste your {integration['display_name']} token",
        password=True,
    )
    if not token.strip():
        console.print("[red]No token entered. Aborting.[/red]")
        return False

    _update_env(integration["credential_env"], token.strip())

    entry = {
        "name": name,
        "transport": integration["mcp_transport"],
        "command": integration["mcp_command"],
        "args": integration["mcp_args"],
        "env_vars": {integration["credential_env"]: integration["credential_env"]},
        "tools": {
            "reversible": integration["reversible_tools"],
            "irreversible": integration["irreversible_tools"],
        },
    }
    data = _load_integrations()
    data.setdefault("servers", [])
    data["servers"] = [s for s in data["servers"] if s["name"] != name]
    data["servers"].append(entry)
    _save_integrations(data)

    display = integration["display_name"]
    console.print(Panel(
        f"[bold green]{display} connected.[/bold green]\n\n"
        "Run [bold cyan]alfard status[/bold cyan] to confirm.",
        border_style="green",
    ))
    return True


def _connect_oauth(name: str, integration: dict) -> bool:
    console.print(Panel(
        f"[bold]{integration['display_name']}[/bold] uses the [bold cyan]gws[/bold cyan] CLI "
        "for local OAuth. Your credentials are stored on your machine only.",
        title=integration["display_name"],
        border_style="cyan",
    ))

    if not shutil.which("gws"):
        console.print(
            "\n[yellow]gws is not installed.[/yellow]\n"
            "Install gws with: [bold]npm install -g @googleworkspace/cli[/bold]\n"
        )
        answer = Prompt.ask("Have you installed gws?", choices=["y", "n"], default="n")
        if answer != "y":
            console.print(
                f"\nRun the install command above then re-run "
                f"[bold cyan]alfard connect {name}[/bold cyan]"
            )
            return False

    console.print("\nOpening browser for Google OAuth — sign in and click Allow.")
    result = subprocess.run(["gws", "auth", "setup"])
    if result.returncode != 0:
        console.print("[yellow]Warning: gws auth setup exited with an error. Continuing.[/yellow]")

    _update_env(integration["credential_env"], "gws-managed")

    entry = {
        "name": name,
        "transport": integration["mcp_transport"],
        "command": integration["mcp_command"],
        "args": integration["mcp_args"],
        "env_vars": {integration["credential_env"]: integration["credential_env"]},
        "tools": {
            "reversible": integration["reversible_tools"],
            "irreversible": integration["irreversible_tools"],
        },
    }
    data = _load_integrations()
    data.setdefault("servers", [])
    data["servers"] = [s for s in data["servers"] if s["name"] != name]
    data["servers"].append(entry)
    _save_integrations(data)

    display = integration["display_name"]
    console.print(Panel(
        f"[bold green]{display} connected.[/bold green]\n\n"
        "Run [bold cyan]alfard status[/bold cyan] to confirm.",
        border_style="green",
    ))
    return True


@click.command()
@click.argument("integration", required=False)
def connect(integration: str | None):
    """Connect an integration via MCP.

    Run without arguments to see available integrations.

    Examples:
      alfard connect notion
      alfard connect github
      alfard connect gmail
    """
    if not integration:
        table = Table(
            title="Available integrations",
            border_style="cyan",
            show_header=True,
        )
        table.add_column("Name", style="bold")
        table.add_column("Description")
        table.add_column("Auth")
        table.add_column("Status")

        data = _load_integrations()
        connected = {s["name"] for s in data.get("servers", [])}

        for name, info in CATALOGUE.items():
            auth_label = "API key" if info["auth"] == AUTH_APIKEY else "OAuth"
            status = "[green]connected[/green]" if name in connected else "[dim]not connected[/dim]"
            table.add_row(name, info["description"], auth_label, status)

        console.print(table)
        console.print("\nRun [bold cyan]alfard connect <name>[/bold cyan] to connect one.\n")
        return

    integration = integration.lower().strip()

    if integration not in CATALOGUE:
        console.print(Panel(
            f"[red]Unknown integration: '{integration}'[/red]\n\n"
            "Run [bold cyan]alfard connect[/bold cyan] to see available integrations.",
            border_style="red",
        ))
        raise SystemExit(1)

    info = CATALOGUE[integration]

    if _already_connected(integration):
        overwrite = Prompt.ask(
            f"[yellow]{info['display_name']} is already connected. Reconnect?[/yellow]",
            choices=["y", "n"],
            default="n",
        )
        if overwrite != "y":
            return

    if info["auth"] == AUTH_APIKEY:
        _connect_apikey(integration, info)
    else:
        _connect_oauth(integration, info)
