"""Lists all configured agents and their status."""

import click
from rich.console import Console
from rich.table import Table
from alfard.agents.loader import AGENTS_DIR, list_agents as _list_agents

console = Console()


@click.command()
def list_agents():
    """List all available agents."""

    agents = _list_agents()

    if not agents:
        console.print("[dim]No agents found. Run [bold cyan]alfard create[/bold cyan] to create one.[/dim]")
        return

    table = Table(title="Agents", border_style="cyan", show_header=True)
    table.add_column("Name", style="bold")
    table.add_column("Soul", style="dim")
    table.add_column("Files")

    for name in agents:
        agent_dir = AGENTS_DIR / name
        soul_path = agent_dir / "soul.md"
        soul_preview = ""
        if soul_path.exists():
            lines = soul_path.read_text(encoding="utf-8").strip().splitlines()
            for line in lines:
                if line.startswith("## Purpose"):
                    continue
                if line.strip() and not line.startswith("#"):
                    soul_preview = line.strip()[:60]
                    break
        files = [f.name for f in sorted(agent_dir.iterdir()) if f.is_file()]
        table.add_row(name, soul_preview, ", ".join(files))

    console.print(table)
