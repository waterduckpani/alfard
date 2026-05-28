"""Displays the audit log — LLM calls, tool calls, and gate decisions."""

import click
from alfard.cli.help_formatter import AlfardCommand
import json
import time
from pathlib import Path
from datetime import datetime
from rich.text import Text
import yaml
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot
from alfard.paths import ALFARD_HOME

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"


def _get_log_path() -> Path | None:
    if not _CONFIG_PATH.exists():
        return None
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    log_path_str = cfg.get("audit", {}).get("log_path", "logs/audit.jsonl")
    return ALFARD_HOME / log_path_str


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
        text.append(f"{timestamp} ", style=p.fg_faint)
        text.append("llm  ", style=f"bold {p.info}")
        text.append(f"{event.get('provider')} / {event.get('model')} ", style=p.fg_dim)
        text.append(f"→ {event.get('response_type', '?')}", style=p.rule)
        text.append(f"  [{event.get('message_count', 0)} messages]", style=p.fg_dim)

    elif event_type == "tool_call":
        text.append(f"{timestamp} ", style=p.fg_faint)
        text.append("tool ", style=f"bold {p.warn}")
        text.append(f"{event.get('tool_name')} ", style=f"bold {p.fg_em}")
        source = event.get("source", "unknown")
        source_style = p.ok if source == "user_instruction" else p.err
        text.append(f"[{source}]", style=source_style)

    elif event_type == "gate_decision":
        text.append(f"{timestamp} ", style=p.fg_faint)
        decision = event.get("decision", "unknown")
        if decision == "approved":
            text.append("gate ", style=f"bold {p.ok}")
            text.append(f"{event.get('tool_name')} ", style=f"bold {p.fg_em}")
            text.append("approved", style=p.ok)
        else:
            text.append("gate ", style=f"bold {p.err}")
            text.append(f"{event.get('tool_name')} ", style=f"bold {p.fg_em}")
            text.append("rejected", style=p.err)
        source = event.get("source", "unknown")
        source_style = p.ok if source == "user_instruction" else p.err
        text.append(f" [{source}]", style=source_style)

    else:
        text.append(f"{timestamp} ", style=p.fg_faint)
        text.append(f"{event_type.upper()} ", style=f"bold {p.fg_em}")
        text.append(str(event), style=p.fg_dim)

    return text


@click.command(cls=AlfardCommand)
@click.argument("agent", required=False)
@click.option("--last", "-n", default=20, help="Show last N events (default: 20)")
@click.option("--tail", "-f", is_flag=True, default=False,
              help="Follow log in real time (like tail -f)")
@click.option("--type", "-t", "event_type", default=None,
              help="Filter by event type: llm_call, tool_call, gate_decision")
def log(agent: str | None, last: int, tail: bool, event_type: str | None):
    """View the audit log — every action your agents have taken.

    Shows what the agent has been doing — every LLM call,
    tool call, and approval gate decision.

    \b
    Examples:
      alfard log                    # show last 20 events
      alfard log --last 50          # show last 50 events
      alfard log --tail             # follow in real time
      alfard log --type tool_call   # show only tool calls
      alfard log --type gate_decision
    """
    log_path = _get_log_path()

    if not log_path or not log_path.exists():
        console.print(
            f"[{p.warn}]no audit log found.[/]\n"
            f"[{p.fg_dim}]run an agent first to generate log entries.[/]\n"
            f"[{p.fg_faint}]expected path: logs/audit.jsonl[/]"
        )
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
            f"[{p.fg_dim}]following {log_path.name} — press ctrl+c to stop[/]\n"
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
            console.print(f"\n[{p.fg_dim}]stopped.[/]")
        return

    events = read_events(event_type)

    if not events:
        console.print(f"[{p.fg_dim}]no log entries found.[/]")
        return

    events = events[-last:]

    console.print(
        f"\n[{p.fg_dim}]showing last {len(events)} events from "
        f"{log_path.name}[/]\n"
    )

    for event in events:
        console.print(_format_event(event))

    console.print(
        f"\n[{p.fg_faint}]total: {len(events)} events shown. "
        f"run with --tail to follow live.[/]\n"
    )
