"""Opens a file belonging to a named agent in the user's editor."""

import os
import subprocess
import click
from alfard.cli.help_formatter import AlfardCommand
from alfard.agents.loader import AGENTS_DIR, list_agents
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, alfard_select
from alfard.cli.cmd_create import _web_wizard

FILE_MAP = {
    "soul": "soul.md",
    "brain": "brain.md",
    "memory": "memory.md",
}


@click.command(cls=AlfardCommand)
@click.argument("agent", required=False)
@click.argument("file", required=False, type=click.Choice(["soul", "brain", "memory", "web"]))
def edit(agent: str | None, file: str | None):
    """Edit an agent's soul, brain or memory files.

    AGENT is the agent name. FILE is one of: soul, brain, memory.

    Example: alfard edit postman soul
    """

    if not agent:
        agents = list_agents()
        if not agents:
            console.print(
                f"[{p.fg_faint}]no agents found. run alfard create first.[/]"
            )
            return
        agent = alfard_select("which agent?", agents)
        if not agent:
            return

    agent_dir = AGENTS_DIR / agent
    if not agent_dir.exists():
        console.print(
            f"[{p.err}]agent '{agent}' not found.[/]\n"
            f"[{p.fg_faint}]run alfard list to see available agents.[/]"
        )
        raise SystemExit(1)

    if not file:
        file = alfard_select("which file?", ["soul", "brain", "memory", "web"])
        if not file:
            return

    if file == "web":
        _web_wizard(agent_dir)
        return

    filename = FILE_MAP[file]
    filepath = agent_dir / filename

    if file == "soul":
        console.print(
            f"[{p.warn}]editing soul.md — this file defines the agent's identity and rules.[/]\n"
            f"[{p.fg_dim}]the agent reads this file but can never modify it. changes take effect on the next run.[/]\n"
        )

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
        console.print(f"{dot('ok')} [{p.fg_dim}]saved: agents/{agent}/{filename}[/]")
    except FileNotFoundError:
        console.print(
            f"[{p.err}]editor '{editor}' not found.[/] "
            f"[{p.fg_dim}]set your $EDITOR environment variable or edit the file directly:[/]\n"
            f"[{p.fg_faint}]{filepath}[/]"
        )
        raise SystemExit(1)
