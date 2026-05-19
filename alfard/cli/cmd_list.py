"""Lists all configured agents and their status."""

import click
from rich import box
from rich.panel import Panel
from rich.text import Text
from rich.console import Group

from alfard.cli.help_formatter import AlfardCommand
from alfard.agents.loader import AGENTS_DIR, list_agents as _list_agents, AgentLoader
from alfard.cli.theme import p, c, console, capabilities


def _border() -> str:
    return p.rule if capabilities.truecolor else "dim"


def _soul_first_line(agent_dir) -> str:
    soul_path = agent_dir / "soul.md"
    if not soul_path.exists():
        return ""
    for line in soul_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:72]
    return ""


@click.command(cls=AlfardCommand)
def list_agents():
    """List all your agents."""

    agents = _list_agents()

    if not agents:
        console.print(
            f"\n[{p.fg_faint}]no agents found. run alfard create to create one.[/]\n"
        )
        return

    blocks: list[Text] = []
    for i, name in enumerate(agents):
        agent_dir = AGENTS_DIR / name
        soul = _soul_first_line(agent_dir)
        try:
            skills = AgentLoader(name).get_agent_skills()
        except Exception:
            skills = []

        block = Text()
        block.append(name, style=f"bold {p.fg_em}")
        if soul:
            block.append(f"\n{soul}", style=p.fg_dim)
        if skills:
            block.append(f"\n{', '.join(skills)}", style=p.fg_faint)

        blocks.append(block)
        if i < len(agents) - 1:
            blocks.append(Text(""))

    console.print()
    console.print(Panel(
        Group(*blocks),
        box=box.ROUNDED,
        border_style=_border(),
        padding=(0, 1),
    ))
    n = len(agents)
    console.print(
        f"[{p.fg_faint}]{n} agent{'s' if n != 1 else ''}  ·  alfard run <name> to start[/]\n"
    )
