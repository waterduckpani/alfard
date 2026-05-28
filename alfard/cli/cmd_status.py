"""Shows the current runtime status of all running agents."""

import os
import click
from alfard.cli.help_formatter import AlfardCommand
import yaml
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from alfard.agents.loader import list_agents, AGENTS_DIR
from alfard.integrations.catalogue import CATALOGUE
from alfard.cli.theme import p, c, console, capabilities
from alfard.cli.components import dot
from alfard.paths import ALFARD_HOME, load_env

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"
_INTEGRATIONS_PATH = ALFARD_HOME / "config" / "integrations.yaml"


def _connected_set() -> set[str]:
    connected: set[str] = set()
    if _INTEGRATIONS_PATH.exists():
        with open(_INTEGRATIONS_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for s in data.get("servers", []):
            name = s.get("name", "")
            if name:
                connected.add(name)
    load_env()
    if os.environ.get("SLACK_BOT_TOKEN"):
        connected.add("slack")
    return connected


def _border() -> str:
    return p.rule if capabilities.truecolor else "dim"


@click.command(cls=AlfardCommand)
def status():
    """Show your current setup — provider, integrations and agents."""

    console.print()

    # ── Provider ──────────────────────────────────────────────────────────────
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        prov = cfg.get("provider", {})
        name = prov.get("name", "—")
        model = prov.get("model", "—")
        gate = cfg.get("approval_gate", {}).get("enabled", True)
        gate_str = c("ok", "gate on") if gate else c("fg_faint", "gate off")
        line = f"{c('fg_em', name)}  ·  {c('fg_dim', model)}  ·  {gate_str}"
    else:
        line = f"[{p.warn}]no config — run alfard setup[/]"

    console.print(Panel(
        Text.from_markup(line),
        title=f"[{p.fg_dim}]provider[/]",
        box=box.ROUNDED,
        border_style=_border(),
        padding=(0, 1),
    ))

    # ── Integrations ──────────────────────────────────────────────────────────
    connected = _connected_set()
    int_tbl = Table(box=None, show_header=False, padding=(0, 1), expand=False)
    int_tbl.add_column(no_wrap=True)
    int_tbl.add_column(no_wrap=True)
    int_tbl.add_column(no_wrap=True)

    for key, info in CATALOGUE.items():
        is_on = key in connected
        status_dot = dot("ok") if is_on else dot("queued")
        name_markup = c("fg_em", info["display_name"]) if is_on else c("fg_faint", info["display_name"])
        transport = info.get("mcp_transport", "stdio") if is_on else "—"
        transport_markup = c("fg_dim", transport) if is_on else c("fg_faint", "—")
        int_tbl.add_row(
            Text.from_markup(status_dot),
            Text.from_markup(name_markup),
            Text.from_markup(transport_markup),
        )

    console.print(Panel(
        int_tbl,
        title=f"[{p.fg_dim}]integrations[/]",
        box=box.ROUNDED,
        border_style=_border(),
        padding=(0, 1),
    ))

    # ── Agents ────────────────────────────────────────────────────────────────
    agents = list_agents()
    if agents:
        agent_tbl = Table(box=None, show_header=False, padding=(0, 1), expand=False)
        agent_tbl.add_column(no_wrap=True, min_width=12)
        agent_tbl.add_column(no_wrap=False)

        for agent_name in agents:
            soul_path = AGENTS_DIR / agent_name / "soul.md"
            soul_preview = ""
            if soul_path.exists():
                for ln in soul_path.read_text(encoding="utf-8").splitlines():
                    stripped = ln.strip()
                    if stripped and not stripped.startswith("#"):
                        soul_preview = stripped[:60]
                        break
            agent_tbl.add_row(
                Text.from_markup(c("fg_em", agent_name)),
                Text.from_markup(c("fg_dim", soul_preview)),
            )
        content: Table | Text = agent_tbl
    else:
        content = Text.from_markup(f"[{p.fg_faint}]no agents. run alfard create[/]")

    console.print(Panel(
        content,
        title=f"[{p.fg_dim}]agents[/]",
        box=box.ROUNDED,
        border_style=_border(),
        padding=(0, 1),
    ))
    console.print()
