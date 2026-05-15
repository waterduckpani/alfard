"""CLI command for managing agent skills."""

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from alfard.agents.loader import (
    AgentLoader, list_agents, list_available_skills,
    add_skill, remove_skill, AGENTS_DIR
)

console = Console()


@click.group()
def skill():
    """Manage skills for agents.

    Skills teach agents how to use specific integrations correctly.

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
                f"[red]Agent '{agent}' not found.[/red]",
                border_style="red"
            ))
            raise SystemExit(1)
        loader = AgentLoader(agent)
        active = loader.get_agent_skills()
        available = list_available_skills()
        table = Table(
            title=f"Skills for {agent}",
            border_style="cyan",
            show_header=True
        )
        table.add_column("Skill", style="bold")
        table.add_column("Status")
        for s in available:
            status = "[green]active[/green]" if s in active \
                else "[dim]not added[/dim]"
            table.add_row(s, status)
        console.print(table)
        console.print(
            f"\nAdd: [bold cyan]alfard skill add {agent} <skill>[/bold cyan]\n"
        )
    else:
        available = list_available_skills()
        if not available:
            console.print("[dim]No skills found in skills/ directory.[/dim]")
            return
        table = Table(
            title="Available skills",
            border_style="cyan",
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
            f"[red]Agent '{agent}' not found.[/red]",
            border_style="red"
        ))
        raise SystemExit(1)
    result = add_skill(agent, skill_name)
    if not result:
        console.print(Panel(
            f"[red]Skill '{skill_name}' not found.[/red]\n\n"
            f"Run [bold cyan]alfard skill list[/bold cyan] "
            f"to see available skills.",
            border_style="red"
        ))
        raise SystemExit(1)
    console.print(Panel(
        f"[green]Added skill '{skill_name}' to {agent}.[/green]\n\n"
        f"Restart the agent for changes to take effect.",
        border_style="green"
    ))


@skill.command(name="remove")
@click.argument("agent")
@click.argument("skill_name")
def remove(agent: str, skill_name: str):
    """Remove a skill from an agent."""
    if agent not in list_agents():
        console.print(Panel(
            f"[red]Agent '{agent}' not found.[/red]",
            border_style="red"
        ))
        raise SystemExit(1)
    result = remove_skill(agent, skill_name)
    if not result:
        console.print(
            f"[yellow]Skill '{skill_name}' is not active "
            f"for {agent}.[/yellow]"
        )
        return
    console.print(
        f"[green]Removed skill '{skill_name}' from {agent}.[/green]"
    )
