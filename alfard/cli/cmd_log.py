"""Displays the audit log — LLM calls, tool calls, and gate decisions."""

import click
import json
import time
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
import yaml

console = Console()

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "alfard.yaml"


def _get_log_path() -> Path | None:
    if not _CONFIG_PATH.exists():
        return None
    with open(_CONFIG_PATH) as f:
        cfg = yaml.safe_load(f) or {}
    log_path_str = cfg.get("audit", {}).get("log_path", "logs/audit.jsonl")
    return Path(__file__).parent.parent.parent / log_path_str


def _format_event(event: dict) -> Text:
    text = Text()
    timestamp = event.get("timestamp", "")
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp = dt.strftime("%H:%M:%S")
        except Exception:
            pass

    event_type = event.get("type", "unknown")

    if event_type == "llm_call":
        text.append(f"{timestamp} ", style="dim")
        text.append("LLM  ", style="bold blue")
        text.append(f"{event.get('provider')} / {event.get('model')} ", style="dim")
        text.append(f"→ {event.get('response_type', '?')}", style="cyan")
        text.append(f"  [{event.get('message_count', 0)} messages]", style="dim")

    elif event_type == "tool_call":
        text.append(f"{timestamp} ", style="dim")
        text.append("TOOL ", style="bold yellow")
        text.append(f"{event.get('tool_name')} ", style="bold")
        source = event.get("source", "unknown")
        source_style = "green" if source == "user_instruction" else "red"
        text.append(f"[{source}]", style=source_style)

    elif event_type == "gate_decision":
        text.append(f"{timestamp} ", style="dim")
        decision = event.get("decision", "unknown")
        if decision == "approved":
            text.append("GATE ", style="bold green")
            text.append(f"{event.get('tool_name')} ", style="bold")
            text.append("approved", style="green")
        else:
            text.append("GATE ", style="bold red")
            text.append(f"{event.get('tool_name')} ", style="bold")
            text.append("rejected", style="red")
        source = event.get("source", "unknown")
        source_style = "green" if source == "user_instruction" else "red"
        text.append(f" [{source}]", style=source_style)

    else:
        text.append(f"{timestamp} ", style="dim")
        text.append(f"{event_type.upper()} ", style="bold")
        text.append(str(event), style="dim")

    return text


@click.command()
@click.argument("agent", required=False)
@click.option("--last", "-n", default=20, help="Show last N events (default: 20)")
@click.option("--tail", "-f", is_flag=True, default=False,
              help="Follow log in real time (like tail -f)")
@click.option("--type", "-t", "event_type", default=None,
              help="Filter by event type: llm_call, tool_call, gate_decision")
def log(agent: str | None, last: int, tail: bool, event_type: str | None):
    """View the audit log.

    Shows what the agent has been doing — every LLM call,
    tool call, and approval gate decision.

    Examples:
      alfard log                    # show last 20 events
      alfard log --last 50          # show last 50 events
      alfard log --tail             # follow in real time
      alfard log --type tool_call   # show only tool calls
      alfard log --type gate_decision
    """
    log_path = _get_log_path()

    if not log_path or not log_path.exists():
        console.print(Panel(
            "[yellow]No audit log found.[/yellow]\n\n"
            "Run an agent first to generate log entries.\n"
            "[dim]Expected path: logs/audit.jsonl[/dim]",
            border_style="yellow"
        ))
        return

    def read_events(filter_type: str | None = None) -> list[dict]:
        events = []
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if filter_type and event.get("type") != filter_type:
                        continue
                    events.append(event)
                except json.JSONDecodeError:
                    continue
        return events

    if tail:
        console.print(
            f"[dim]Following {log_path.name} — press Ctrl+C to stop[/dim]\n"
        )
        try:
            with open(log_path, encoding="utf-8") as f:
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if line:
                        line = line.strip()
                        if line:
                            try:
                                event = json.loads(line)
                                if not event_type or event.get("type") == event_type:
                                    console.print(_format_event(event))
                            except json.JSONDecodeError:
                                pass
                    else:
                        time.sleep(0.2)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped.[/dim]")
        return

    events = read_events(event_type)

    if not events:
        console.print("[dim]No log entries found.[/dim]")
        return

    events = events[-last:]

    console.print(
        f"\n[dim]Showing last {len(events)} events from "
        f"{log_path.name}[/dim]\n"
    )

    for event in events:
        console.print(_format_event(event))

    console.print(
        f"\n[dim]Total: {len(events)} events shown. "
        f"Run with --tail to follow live.[/dim]\n"
    )
