"""CLI commands for managing agent folder mounts."""

import click
import yaml
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from alfard.cli import theme
from alfard.agents.loader import list_agents, AGENTS_DIR

console = Console()
MOUNTS_FILE = "mounts.yaml"


def _load_mounts(agent_name: str) -> dict:
    path = AGENTS_DIR / agent_name / MOUNTS_FILE
    if not path.exists():
        return {"mounts": []}
    with open(path) as f:
        return yaml.safe_load(f) or {"mounts": []}


def _save_mounts(agent_name: str, data: dict) -> None:
    path = AGENTS_DIR / agent_name / MOUNTS_FILE
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


@click.group()
def mount():
    """Manage folder mounts for agents.

    Mounts give agents access to specific folders on your machine.
    All file operations are restricted to declared paths.

    \b
    Examples:
      alfard mount add postman ~/Documents/work --access readwrite
      alfard mount add postman ~/Desktop/Projects/Stocky --access readonly
      alfard mount list postman
      alfard mount remove postman ~/Documents/work
    """
    pass


@mount.command(name="add")
@click.argument("agent")
@click.argument("path")
@click.option("--access", "-a",
              type=click.Choice(["readonly", "readwrite"]),
              default="readonly",
              help="Access level: readonly or readwrite (default: readonly)")
def add(agent: str, path: str, access: str):
    """Mount a folder for an agent."""
    if agent not in list_agents():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)

    # Resolve and validate path
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        console.print(Panel(
            f"[{theme.ERROR}]Path does not exist: {path}[/{theme.ERROR}]\n\n"
            f"Create the folder first:\n"
            f"  mkdir -p {resolved}",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)

    if not resolved.is_dir():
        console.print(Panel(
            f"[{theme.ERROR}]Path is not a directory: {path}[/{theme.ERROR}]",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)

    data = _load_mounts(agent)
    existing_paths = [m["path"] for m in data.get("mounts", [])]

    # Normalise path for storage
    stored_path = str(Path(path).expanduser())

    if stored_path in existing_paths:
        console.print(
            f"[{theme.WARNING}]Already mounted: {path}[/{theme.WARNING}]"
        )
        raise SystemExit(1)

    data.setdefault("mounts", []).append({
        "path": stored_path,
        "access": access,
    })
    _save_mounts(agent, data)

    access_icon = "✓ read+write" if access == "readwrite" else "· read only"

    console.print(Panel(
        f"[bold {theme.SUCCESS}]Mount added.[/bold {theme.SUCCESS}]\n\n"
        f"Agent:   {agent}\n"
        f"Path:    {resolved}\n"
        f"Access:  {access_icon}\n\n"
        f"[{theme.DIM}]The agent can now access files in this folder.[/{theme.DIM}]",
        border_style=theme.PANEL_SUCCESS
    ))


@mount.command(name="remove")
@click.argument("agent")
@click.argument("path")
def remove(agent: str, path: str):
    """Remove a folder mount from an agent."""
    if agent not in list_agents():
        console.print(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]"
        )
        raise SystemExit(1)

    stored_path = str(Path(path).expanduser())
    data = _load_mounts(agent)
    original = len(data.get("mounts", []))
    data["mounts"] = [
        m for m in data.get("mounts", [])
        if m["path"] != stored_path
    ]

    if len(data["mounts"]) == original:
        console.print(
            f"[{theme.WARNING}]Mount not found: {path}[/{theme.WARNING}]"
        )
        raise SystemExit(1)

    _save_mounts(agent, data)
    console.print(
        f"[{theme.SUCCESS}]✓ Removed mount: {path}[/{theme.SUCCESS}]"
    )


@mount.command(name="list")
@click.argument("agent", required=False)
def list_mounts(agent: str | None):
    """List folder mounts for an agent or all agents."""
    agents = [agent] if agent else list_agents()
    any_mounts = False

    for a in agents:
        data = _load_mounts(a)
        mounts = data.get("mounts", [])
        if not mounts:
            continue
        any_mounts = True

        table = Table(
            title=f"Mounts — {a}",
            border_style=theme.BORDER,
            show_header=True,
        )
        table.add_column("Path", style="bold")
        table.add_column("Access")
        table.add_column("Exists")

        for m in mounts:
            p = Path(m["path"]).expanduser()
            exists = (
                f"[{theme.SUCCESS}]✓[/{theme.SUCCESS}]"
                if p.exists()
                else f"[{theme.ERROR}]✗ missing[/{theme.ERROR}]"
            )
            access = m.get("access", "readonly")
            access_str = (
                f"[{theme.SUCCESS}]read+write[/{theme.SUCCESS}]"
                if access == "readwrite"
                else f"[{theme.DIM}]read only[/{theme.DIM}]"
            )
            table.add_row(m["path"], access_str, exists)

        console.print(table)

    if not any_mounts:
        console.print(
            f"[{theme.DIM}]No mounts configured. "
            f"Add one: alfard mount add <agent> <path>[/{theme.DIM}]"
        )
