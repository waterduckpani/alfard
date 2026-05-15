"""Shows the current runtime status of all running agents."""

import shutil
import click
import yaml
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from alfard.agents.loader import list_agents
from alfard.cli import theme

console = Console()
_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "alfard.yaml"
_INTEGRATIONS_PATH = Path(__file__).parent.parent.parent / "config" / "integrations.yaml"


@click.command()
def status():
    """Show your current setup — provider, integrations and agents."""

    console.print(Panel(
        f"[bold {theme.PRIMARY}]alfard status[/bold {theme.PRIMARY}]",
        border_style=theme.BORDER
    ))

    # Provider block
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        provider = cfg.get("provider", {})
        table = Table(show_header=False, border_style=theme.DIM, box=None)
        table.add_column("Key", style="bold", width=20)
        table.add_column("Value")
        table.add_row("Provider", provider.get("name", "—"))
        table.add_row("Model", provider.get("model", "—"))
        table.add_row("Approval gate", str(cfg.get("approval_gate", {}).get("enabled", True)))
        console.print("\n[bold]LLM[/bold]")
        console.print(table)
    else:
        console.print(
            f"\n[{theme.WARNING}]No config found. Run "
            f"[bold {theme.PRIMARY}]alfard setup[/bold {theme.PRIMARY}] first.[/{theme.WARNING}]"
        )

    # Integrations block
    console.print("\n[bold]Integrations[/bold]")
    servers = []
    if _INTEGRATIONS_PATH.exists():
        with open(_INTEGRATIONS_PATH) as f:
            integrations_cfg = yaml.safe_load(f) or {}
        servers = integrations_cfg.get("servers", [])

    gws_creds = Path.home() / ".config" / "gws" / "credentials.enc"
    gws_installed = shutil.which("gws") is not None

    if servers or (gws_installed and gws_creds.exists()):
        itab = Table(show_header=True, border_style=theme.DIM)
        itab.add_column("Name", style="bold")
        itab.add_column("Transport")
        itab.add_column("URL / Command")
        for s in servers:
            loc = s.get("url") or s.get("command", "—")
            itab.add_row(s.get("name", "—"), s.get("transport", "—"), loc)
        if gws_installed and gws_creds.exists():
            itab.add_row("gmail", "gws", "gws gmail +triage")
            itab.add_row("gdrive", "gws", "gws drive files list")
        console.print(itab)
    else:
        console.print(
            f"[{theme.DIM}]No integrations configured. Run "
            f"[bold {theme.PRIMARY}]alfard connect <name>[/bold {theme.PRIMARY}][/{theme.DIM}]"
        )

    # Agents block
    console.print("\n[bold]Agents[/bold]")
    agents = list_agents()
    if agents:
        console.print("  " + "  ".join(f"[{theme.PRIMARY}]{a}[/{theme.PRIMARY}]" for a in agents))
    else:
        console.print(
            f"[{theme.DIM}]  No agents. Run [bold {theme.PRIMARY}]alfard create[/bold {theme.PRIMARY}][/{theme.DIM}]"
        )
    console.print()
