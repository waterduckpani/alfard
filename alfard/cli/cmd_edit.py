"""Opens a file belonging to a named agent in the user's editor."""

import os
import subprocess
import click
from rich.console import Console
from rich.panel import Panel
from alfard.agents.loader import AGENTS_DIR

console = Console()

FILE_MAP = {
    "soul": "soul.md",
    "brain": "brain.md",
    "memory": "memory.md",
}


@click.command()
@click.argument("agent")
@click.argument("file", type=click.Choice(["soul", "brain", "memory"]))
def edit(agent: str, file: str):
    """Open an agent file in your default editor.

    AGENT is the agent name. FILE is one of: soul, brain, memory.

    Example: alfard edit postman soul
    """

    agent_dir = AGENTS_DIR / agent
    if not agent_dir.exists():
        console.print(Panel(
            f"[red]Agent '{agent}' not found.[/red]\n\n"
            f"Run [bold cyan]alfard list[/bold cyan] to see available agents.\n"
            f"Run [bold cyan]alfard create[/bold cyan] to create a new one.",
            border_style="red"
        ))
        raise SystemExit(1)

    filename = FILE_MAP[file]
    filepath = agent_dir / filename

    if file == "soul":
        console.print(Panel(
            "[bold yellow]You are editing soul.md[/bold yellow]\n\n"
            "This file defines the agent's identity and rules.\n"
            "The agent reads this file but can never modify it.\n"
            "Changes take effect on the next run.",
            border_style="yellow",
            title="⚠ Identity file"
        ))

    if not filepath.exists():
        filepath.write_text(f"# {agent} — {file}\n\n", encoding="utf-8")

    import shutil
    _raw_editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or ""
    if not _raw_editor:
        if shutil.which("code"):
            _raw_editor = "code"
        elif shutil.which("nano"):
            _raw_editor = "nano"
        else:
            _raw_editor = "vi"
    editor = _raw_editor
    editor_cmd = [editor, str(filepath)]
    if editor in ("code", "code-insiders"):
        editor_cmd = [editor, "--wait", str(filepath)]

    try:
        subprocess.run(editor_cmd, check=True)
        console.print(f"[green]Saved:[/green] agents/{agent}/{filename}")
    except FileNotFoundError:
        console.print(
            f"[red]Editor '{editor}' not found.[/red] "
            f"Set your $EDITOR environment variable or edit the file directly:\n"
            f"[dim]{filepath}[/dim]"
        )
        raise SystemExit(1)
