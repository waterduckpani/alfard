"""Creates a new agent definition interactively."""

import re
from pathlib import Path
import click
from alfard.cli.help_formatter import AlfardCommand
import questionary
from alfard.agents.loader import (
    AGENTS_DIR, list_agents, list_available_skills, add_skill,
)
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, alfard_input, alfard_select, alfard_multiselect


@click.command(cls=AlfardCommand)
def create():
    """Create a new agent interactively."""

    console.print(f"\n[{p.fg_em}]create a new agent[/]\n")

    while True:
        name = alfard_input(
            "agent name",
            hint="lowercase, hyphens ok, e.g. my-agent   ·   leave blank to go back",
        ).strip().lower()
        if not name:
            return
        if not re.match(r'^[a-z0-9-]+$', name):
            console.print(f"  [{p.err}]name must be lowercase letters, numbers, or hyphens only.[/]")
            continue
        agent_dir = AGENTS_DIR / name
        if agent_dir.exists():
            console.print(f"  [{p.err}]agent '{name}' already exists.[/]")
            continue
        break

    description = alfard_input("what does this agent do?").strip()

    personality = alfard_input(
        "personality or tone",
        default="helpful and concise",
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

    # Step 1 — copy skills from an existing agent
    copied_skills: set[str] = set()
    agents_with_skills = [
        a for a in list_agents()
        if a != name and (AGENTS_DIR / a / "skills").exists()
        and any((AGENTS_DIR / a / "skills").glob("*.md"))
    ]
    if agents_with_skills:
        console.print()
        source = alfard_select(
            "copy skills from an existing agent? (optional)",
            ["skip"] + agents_with_skills,
            default="skip",
        )
        if source and source != "skip":
            src_skills_dir = AGENTS_DIR / source / "skills"
            dest_skills_dir = agent_dir / "skills"
            dest_skills_dir.mkdir(exist_ok=True)
            for skill_file in sorted(src_skills_dir.glob("*.md")):
                (dest_skills_dir / skill_file.name).write_text(
                    skill_file.read_text(encoding="utf-8"), encoding="utf-8"
                )
                copied_skills.add(skill_file.stem)

    # Step 2 — add skills from the global library
    available = list_available_skills()
    if available:
        choices = []
        for s in available:
            if s in copied_skills:
                choices.append(questionary.Choice(
                    s, value=s, checked=True, disabled="copied above"
                ))
            else:
                choices.append(questionary.Choice(s, value=s))
        console.print()
        selected = alfard_multiselect(
            "add skills from the library:",
            choices,
        )
        if selected:
            for s in selected:
                if s not in copied_skills:
                    add_skill(name, s)

    console.print()
    console.print(f"{dot('ok')} [{p.fg_dim}]alfard created {name}.[/]\n")
    console.print(f"[{p.fg_faint}]agents/{name}/[/]")
    console.print(f"  [{p.fg_dim}]soul.md[/]    — defines who your agent is")
    console.print(f"  [{p.fg_dim}]brain.md[/]   — permanent knowledge you give the agent")
    console.print(f"  [{p.fg_dim}]memory.md[/]  — managed automatically; do not edit by hand")
    console.print(f"\n  [{p.fg_em}]alfard edit {name} soul[/]    [{p.fg_faint}]open soul.md now[/]")
    console.print(f"  [{p.fg_em}]alfard run {name}[/]          [{p.fg_faint}]start chatting[/]")
