"""CLI command for managing agent skills."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from alfard.agents.loader import (
    AgentLoader, list_agents, list_available_skills,
    add_skill, remove_skill, AGENTS_DIR
)
from alfard.cli import theme

console = Console()


@click.group()
def skill():
    """Manage skills — teach agents how to use integrations correctly.

    \b
    Examples:
      alfard skill list
      alfard skill list postman
      alfard skill add postman notion
      alfard skill remove postman notion
    """
    pass


@skill.command(name="list")
@click.argument("agent", required=False)
def list_skills(agent: str | None):
    """List available skills or skills for a specific agent."""
    if agent:
        if agent not in list_agents():
            console.print(Panel(
                f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
                border_style=theme.PANEL_ERROR
            ))
            raise SystemExit(1)
        loader = AgentLoader(agent)
        active = loader.get_agent_skills()
        available = list_available_skills()
        table = Table(
            title=f"Skills for {agent}",
            border_style=theme.BORDER,
            show_header=True
        )
        table.add_column("Skill", style="bold")
        table.add_column("Status")
        for s in available:
            status = (
                f"[{theme.SUCCESS}]active[/{theme.SUCCESS}]"
                if s in active
                else f"[{theme.DIM}]not added[/{theme.DIM}]"
            )
            table.add_row(s, status)
        console.print(table)
        console.print(
            f"\nAdd: [bold {theme.PRIMARY}]alfard skill add {agent} <skill>[/bold {theme.PRIMARY}]\n"
        )
    else:
        available = list_available_skills()
        if not available:
            console.print(f"[{theme.DIM}]No skills found in skills/ directory.[/{theme.DIM}]")
            return
        table = Table(
            title="Available skills",
            border_style=theme.BORDER,
            show_header=True
        )
        table.add_column("Skill", style="bold")
        table.add_column("File")
        for s in available:
            table.add_row(s, f"skills/{s}.md")
        console.print(table)


@skill.command(name="add")
@click.argument("agent")
@click.argument("skill_name")
def add(agent: str, skill_name: str):
    """Add a skill to an agent."""
    if agent not in list_agents():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)
    result = add_skill(agent, skill_name)
    if not result:
        console.print(Panel(
            f"[{theme.ERROR}]Skill '{skill_name}' not found.[/{theme.ERROR}]\n\n"
            f"Run [bold {theme.PRIMARY}]alfard skill list[/bold {theme.PRIMARY}] "
            f"to see available skills.",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)
    console.print(Panel(
        f"[{theme.SUCCESS}]Added skill '{skill_name}' to {agent}.[/{theme.SUCCESS}]\n\n"
        f"Restart the agent for changes to take effect.",
        border_style=theme.PANEL_SUCCESS
    ))


@skill.command(name="remove")
@click.argument("agent")
@click.argument("skill_name")
def remove(agent: str, skill_name: str):
    """Remove a skill from an agent."""
    if agent not in list_agents():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)
    result = remove_skill(agent, skill_name)
    if not result:
        console.print(
            f"[{theme.WARNING}]Skill '{skill_name}' is not active "
            f"for {agent}.[/{theme.WARNING}]"
        )
        return
    console.print(
        f"[{theme.SUCCESS}]Removed skill '{skill_name}' from {agent}.[/{theme.SUCCESS}]"
    )
