"""Creates a new agent definition interactively."""

import re
from pathlib import Path
import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from alfard.agents.loader import AGENTS_DIR
from alfard.cli import theme

console = Console()


@click.command()
def create():
    """Create a new agent interactively."""

    console.print(Panel(
        f"[bold {theme.PRIMARY}]Create a new agent[/bold {theme.PRIMARY}]",
        border_style=theme.BORDER
    ))

    # Ask for agent name — lowercase, no spaces, only letters/numbers/hyphens
    while True:
        name = Prompt.ask("Agent name").strip().lower()
        if not name:
            console.print(f"[{theme.ERROR}]Name cannot be empty.[/{theme.ERROR}]")
            continue
        if not re.match(r'^[a-z0-9-]+$', name):
            console.print(f"[{theme.ERROR}]Name must be lowercase letters, numbers, or hyphens only.[/{theme.ERROR}]")
            continue
        agent_dir = AGENTS_DIR / name
        if agent_dir.exists():
            console.print(f"[{theme.ERROR}]Agent '{name}' already exists.[/{theme.ERROR}]")
            continue
        break

    description = Prompt.ask("What does this agent do?").strip()

    personality = Prompt.ask(
        "Personality or tone (e.g. concise, professional, friendly)",
        default="helpful and concise"
    ).strip()

    agent_dir.mkdir(parents=True, exist_ok=True)

    soul_content = f"""# {name}

## Purpose
{description}

## Personality
{personality}

## Rules
- Always be honest about what you can and cannot do.
- Never take irreversible actions without explicit user confirmation.
- Keep responses concise and focused on the task.
- If unsure, ask for clarification rather than guessing.
"""
    (agent_dir / "soul.md").write_text(soul_content, encoding="utf-8")

    (agent_dir / "brain.md").write_text(
        f"# {name} — knowledge\n\n",
        encoding="utf-8"
    )
    (agent_dir / "memory.md").write_text(
        f"# {name} — memory\n\n",
        encoding="utf-8"
    )

    console.print()
    console.print(Panel(
        f"[bold {theme.SUCCESS}]Agent '{name}' created.[/bold {theme.SUCCESS}]\n\n"
        f"[{theme.DIM}]soul.md[/{theme.DIM}]    — identity and rules [bold](read-only for agent)[/bold]\n"
        f"[{theme.DIM}]brain.md[/{theme.DIM}]   — persistent knowledge\n"
        f"[{theme.DIM}]memory.md[/{theme.DIM}]  — session memory\n\n"
        f"Edit soul:  [bold {theme.PRIMARY}]alfard edit {name} soul[/bold {theme.PRIMARY}]\n"
        f"Run agent:  [bold {theme.PRIMARY}]alfard run {name}[/bold {theme.PRIMARY}]",
        border_style=theme.PANEL_SUCCESS,
        title=f"agents/{name}/"
    ))
