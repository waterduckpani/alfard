"""Shows the current runtime status of all running agents."""

import click
import yaml
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from alfard.agents.loader import list_agents

console = Console()
_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "alfard.yaml"
_INTEGRATIONS_PATH = Path(__file__).parent.parent.parent / "config" / "integrations.yaml"


@click.command()
def status():
    """Show current provider, integrations, and agents."""

    console.print(Panel(
        "[bold cyan]alfard status[/bold cyan]",
        border_style="cyan"
    ))

    # Provider block
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        provider = cfg.get("provider", {})
        table = Table(show_header=False, border_style="dim", box=None)
        table.add_column("Key", style="bold", width=20)
        table.add_column("Value")
        table.add_row("Provider", provider.get("name", "—"))
        table.add_row("Model", provider.get("model", "—"))
        table.add_row("Approval gate", str(cfg.get("approval_gate", {}).get("enabled", True)))
        console.print("\n[bold]LLM[/bold]")
        console.print(table)
    else:
        console.print("\n[yellow]No config found. Run [bold]alfard setup[/bold] first.[/yellow]")

    # Integrations block
    console.print("\n[bold]Integrations[/bold]")
    if _INTEGRATIONS_PATH.exists():
        with open(_INTEGRATIONS_PATH) as f:
            integrations_cfg = yaml.safe_load(f) or {}
        servers = integrations_cfg.get("servers", [])
        if servers:
            itab = Table(show_header=True, border_style="dim")
            itab.add_column("Name", style="bold")
            itab.add_column("Transport")
            itab.add_column("URL / Command")
            for s in servers:
                loc = s.get("url") or s.get("command", "—")
                itab.add_row(s.get("name", "—"), s.get("transport", "—"), loc)
            console.print(itab)
        else:
            console.print("[dim]No integrations configured. Run [bold cyan]alfard connect <name>[/bold cyan][/dim]")
    else:
        console.print("[dim]No integrations configured.[/dim]")

    # Agents block
    console.print("\n[bold]Agents[/bold]")
    agents = list_agents()
    if agents:
        console.print("  " + "  ".join(f"[cyan]{a}[/cyan]" for a in agents))
    else:
        console.print("[dim]  No agents. Run [bold cyan]alfard create[/bold cyan][/dim]")
    console.print()
