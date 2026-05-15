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
from alfard.cli import theme

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
        border_style=theme.BORDER,
    ))

    console.print("\n[bold]How to get your token:[/bold]")
    for line in integration["get_token_steps"].splitlines():
        console.print(line)

    url = integration.get("get_token_url", "")
    if url:
        console.print(f"\n[bold {theme.PRIMARY}]{url}[/bold {theme.PRIMARY}]")
        webbrowser.open(url)

    token = Prompt.ask(
        f"\nPaste your {integration['display_name']} token",
        password=True,
    )
    if not token.strip():
        console.print(f"[{theme.ERROR}]No token entered. Aborting.[/{theme.ERROR}]")
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
        f"[bold {theme.SUCCESS}]{display} connected.[/bold {theme.SUCCESS}]\n\n"
        f"Run [bold {theme.PRIMARY}]alfard status[/bold {theme.PRIMARY}] to confirm.",
        border_style=theme.SUCCESS,
    ))
    return True


def _connect_oauth(name: str, integration: dict) -> bool:
    # Step 1: welcome panel
    console.print(Panel(
        integration["description"],
        title=integration["display_name"],
        border_style=theme.BORDER,
    ))

    # Step 2: ensure gws is installed
    if not shutil.which("gws"):
        console.print("[bold]Installing gws (Google Workspace CLI)...[/bold]")
        if not shutil.which("npm"):
            console.print(Panel(
                f"[{theme.ERROR}]npm is not installed.[/{theme.ERROR}]\n\n"
                f"Install Node.js from [bold {theme.PRIMARY}]https://nodejs.org[/bold {theme.PRIMARY}] then re-run "
                f"[bold {theme.PRIMARY}]alfard connect {name}[/bold {theme.PRIMARY}]",
                border_style=theme.ERROR,
            ))
            return False
        result = subprocess.run(["npm", "install", "-g", "@googleworkspace/cli"])
        if result.returncode != 0:
            console.print(Panel(
                f"[{theme.ERROR}]gws installation failed.[/{theme.ERROR}]\n\n"
                "Run [bold]npm install -g @googleworkspace/cli[/bold] manually then retry.",
                border_style=theme.ERROR,
            ))
            return False

    # Step 3: skip GCP setup if credentials already exist
    creds_dest = Path.home() / ".config" / "gws" / "client_secret.json"
    if not creds_dest.exists():
        # Step 4: print one-time GCP setup instructions
        setup_instructions = (
            "You need to create a free Google Cloud project to connect Gmail.\n"
            "This is a one-time setup — you'll never need to do it again.\n\n"
            "Step 1: Create a project\n"
            "  → We'll open Google Cloud Console now\n"
            "  → Click \"New Project\", name it anything (e.g. \"alfard\")\n"
            "  → Click Create\n\n"
            "Step 2: Enable Gmail API\n"
            "  → We'll open the Gmail API page\n"
            "  → Click Enable\n\n"
            "Step 3: Configure consent screen\n"
            "  → Go to APIs & Services → OAuth consent screen\n"
            "  → Choose External → fill in app name \"alfard\" and your email\n"
            "  → Click Save through all screens\n"
            "  → Click \"Add users\" and add YOUR Gmail address as a test user\n\n"
            "Step 4: Create credentials\n"
            "  → Go to APIs & Services → Credentials\n"
            "  → Click Create Credentials → OAuth client ID\n"
            "  → Application type: Desktop app → name it \"alfard\" → Create\n"
            "  → Click the download button (↓) to download the JSON file"
        )
        console.print(Panel(
            setup_instructions,
            title="One-time Google setup (5 minutes)",
            border_style=theme.WARNING,
        ))

        # Step 5: wait for user to confirm they're ready
        Prompt.ask("Ready to start? Press Enter to open Google Cloud Console", default="")

        # Step 6a: GCP console
        webbrowser.open("https://console.cloud.google.com")
        Prompt.ask("Step 1 done — project created? [press Enter to continue]", default="")

        # Step 6b: Gmail API
        webbrowser.open("https://console.cloud.google.com/apis/library/gmail.googleapis.com")
        Prompt.ask("Step 2 done — Gmail API enabled? [press Enter to continue]", default="")

        # Step 6c: OAuth consent screen
        webbrowser.open("https://console.cloud.google.com/auth/clients")
        console.print(
            "\nConfigure the consent screen:\n"
            "  → Choose External\n"
            "  → Fill in app name [bold]alfard[/bold] and your email\n"
            "  → Click Save through all screens\n"
            "  → Click [bold]Add users[/bold] and add your Gmail address as a test user"
        )
        Prompt.ask(
            "Step 3 done — consent screen configured and test user added? [press Enter to continue]",
            default="",
        )

        # Step 6d: credentials
        webbrowser.open("https://console.cloud.google.com/apis/credentials")
        console.print(
            "\nCreate OAuth credentials:\n"
            "  → Click [bold]Create Credentials[/bold] → OAuth client ID\n"
            "  → Application type: [bold]Desktop app[/bold] → name it alfard → Create\n"
            "  → Click the [bold]download button (↓)[/bold] to download the JSON file"
        )
        Prompt.ask("Step 4 done — credentials JSON downloaded? [press Enter to continue]", default="")

        # Step 7: get credentials path and copy to gws config
        creds_path = Prompt.ask(
            "\nDrag and drop your downloaded credentials JSON file here, or paste the path"
        ).strip().strip("'\"")

        if not creds_path or not Path(creds_path).exists():
            console.print(Panel(
                f"[{theme.ERROR}]File not found.[/{theme.ERROR}]\n\nRe-run "
                f"[bold {theme.PRIMARY}]alfard connect {name}[/bold {theme.PRIMARY}] and provide a valid path.",
                border_style=theme.ERROR,
            ))
            return False

        creds_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(creds_path, creds_dest)
        console.print(f"[{theme.SUCCESS}]Credentials saved.[/{theme.SUCCESS}]")

    # Step 8: OAuth login
    console.print(f"\n[{theme.DIM}]Opening browser for Google sign-in...[/{theme.DIM}]")
    result = subprocess.run(["gws", "auth", "login"])
    if result.returncode != 0:
        console.print(Panel(
            f"[{theme.ERROR}]Google sign-in failed.[/{theme.ERROR}]\n\n"
            f"Check the error above, then re-run "
            f"[bold {theme.PRIMARY}]alfard connect {name}[/bold {theme.PRIMARY}]",
            border_style=theme.ERROR,
        ))
        return False

    # Step 9: test the connection
    console.print(f"[{theme.DIM}]Testing connection...[/{theme.DIM}]")
    test = subprocess.run(
        ["gws", "gmail", "+triage", "--max", "1"],
        capture_output=True,
        text=True,
    )
    if test.returncode != 0:
        console.print(Panel(
            f"[{theme.ERROR}]Connection test failed.[/{theme.ERROR}]\n\n{test.stderr.strip()}",
            border_style=theme.ERROR,
        ))
        return False

    # Step 10: write to .env
    _update_env(integration["credential_env"], "gws-managed")

    # Step 11: add server to integrations.yaml
    entry = {
        "name": name,
        "transport": integration["mcp_transport"],
        "command": integration["mcp_command"],
        "args": integration["mcp_args"],
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

    # Step 12: add skill to agent(s)
    from alfard.agents.loader import list_agents, add_skill, AGENTS_DIR  # noqa: F401

    agents = list_agents()
    added_to: str = ""
    if agents:
        console.print("\n[bold]Which agent should get the Gmail skill?[/bold]")
        for i, agent_name in enumerate(agents, start=1):
            console.print(f"  {i}. {agent_name}")
        console.print(f"  {len(agents) + 1}. All agents")

        choice_raw = Prompt.ask("Enter number", default="1")
        try:
            choice = int(choice_raw)
        except ValueError:
            choice = 1

        if choice == len(agents) + 1:
            for agent_name in agents:
                add_skill(agent_name, name)
            added_to = "all agents"
        elif 1 <= choice <= len(agents):
            selected = agents[choice - 1]
            add_skill(selected, name)
            added_to = selected
        else:
            selected = agents[0]
            add_skill(selected, name)
            added_to = selected

    # Step 13: success panel
    display = integration["display_name"]
    skill_line = f"\nSkill added to: {added_to}" if added_to else ""
    run_hint = f"\nRun: [bold {theme.PRIMARY}]alfard run {added_to}[/bold {theme.PRIMARY}]" if added_to else ""
    console.print(Panel(
        f"[bold {theme.SUCCESS}]{display} connected.[/bold {theme.SUCCESS}]\n\n"
        f"Postman can now read and manage your Gmail inbox."
        f"{skill_line}"
        f"{run_hint}",
        border_style=theme.SUCCESS,
    ))
    return True


@click.command()
@click.argument("integration", required=False)
def connect(integration: str | None):
    """Connect an external service like Notion, Gmail or GitHub.

    Run without arguments to see available integrations.

    Examples:
      alfard connect notion
      alfard connect github
      alfard connect gmail
    """
    if not integration:
        table = Table(
            title="Available integrations",
            border_style=theme.BORDER,
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
            status = (
                f"[{theme.SUCCESS}]connected[/{theme.SUCCESS}]"
                if name in connected
                else f"[{theme.DIM}]not connected[/{theme.DIM}]"
            )
            table.add_row(name, info["description"], auth_label, status)

        console.print(table)
        console.print(
            f"\nRun [bold {theme.PRIMARY}]alfard connect <name>[/bold {theme.PRIMARY}] to connect one.\n"
        )
        return

    integration = integration.lower().strip()

    if integration not in CATALOGUE:
        console.print(Panel(
            f"[{theme.ERROR}]Unknown integration: '{integration}'[/{theme.ERROR}]\n\n"
            f"Run [bold {theme.PRIMARY}]alfard connect[/bold {theme.PRIMARY}] to see available integrations.",
            border_style=theme.ERROR,
        ))
        raise SystemExit(1)

    info = CATALOGUE[integration]

    if _already_connected(integration):
        overwrite = Prompt.ask(
            f"[{theme.WARNING}]{info['display_name']} is already connected. Reconnect?[/{theme.WARNING}]",
            choices=["y", "n"],
            default="n",
        )
        if overwrite != "y":
            return

    if info["auth"] == AUTH_APIKEY:
        _connect_apikey(integration, info)
    else:
        _connect_oauth(integration, info)
