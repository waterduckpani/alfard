"""Opens a file belonging to a named agent in the user's editor."""

import os
import subprocess
import click
from rich.console import Console
from rich.panel import Panel
from alfard.agents.loader import AGENTS_DIR
from alfard.cli import theme

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
    """Edit an agent's soul, brain or memory files.

    AGENT is the agent name. FILE is one of: soul, brain, memory.

    Example: alfard edit postman soul
    """

    agent_dir = AGENTS_DIR / agent
    if not agent_dir.exists():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]\n\n"
            f"Run [bold {theme.PRIMARY}]alfard list[/bold {theme.PRIMARY}] to see available agents.\n"
            f"Run [bold {theme.PRIMARY}]alfard create[/bold {theme.PRIMARY}] to create a new one.",
            border_style=theme.ERROR
        ))
        raise SystemExit(1)

    filename = FILE_MAP[file]
    filepath = agent_dir / filename

    if file == "soul":
        console.print(Panel(
            f"[bold {theme.WARNING}]You are editing soul.md[/bold {theme.WARNING}]\n\n"
            "This file defines the agent's identity and rules.\n"
            "The agent reads this file but can never modify it.\n"
            "Changes take effect on the next run.",
            border_style=theme.WARNING,
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
        console.print(f"[{theme.SUCCESS}]Saved:[/{theme.SUCCESS}] agents/{agent}/{filename}")
    except FileNotFoundError:
        console.print(
            f"[{theme.ERROR}]Editor '{editor}' not found.[/{theme.ERROR}] "
            f"Set your $EDITOR environment variable or edit the file directly:\n"
            f"[{theme.DIM}]{filepath}[/{theme.DIM}]"
        )
        raise SystemExit(1)
