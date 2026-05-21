"""CLI commands for viewing and managing agent memory — status overview and proposal review."""

import json
import click
from rich.panel import Panel
from rich.prompt import Prompt
from rich import print as rprint

from alfard.agents.loader import list_agents, AgentLoader
from alfard.cli.theme import p, console, PANEL_GATE, ICON_OK, ICON_FAIL
from alfard.cli.components import alfard_select


_BAR_WIDTH = 16
_TYPE_ORDER = [
    "fact", "procedure", "mistake", "tool_pattern", "goal",
    "decision", "person", "preference", "constraint", "project_state",
]


def _build_bar(count: int, max_count: int) -> str:
    filled = round(count / max_count * _BAR_WIDTH) if max_count > 0 else 0
    return f"[{p.ok}]{'█' * filled}[/][{p.fg_faint}]{'░' * (_BAR_WIDTH - filled)}[/]"


def _run_review(agent: str, loader: AgentLoader) -> None:
    """Run the proposal review flow for an agent."""
    proposals_path = loader.agent_dir / "memory" / "proposals.jsonl"

    if not proposals_path.exists():
        rprint(Panel(
            f"No pending proposals for [bold]{agent}[/bold].",
            border_style=PANEL_GATE,
        ))
        return

    all_proposals: list[dict] = []
    for line in proposals_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            all_proposals.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    pending = [entry for entry in all_proposals if entry.get("status") == "pending"]
    if not pending:
        rprint(Panel(
            f"No pending proposals for [bold]{agent}[/bold].",
            border_style=PANEL_GATE,
        ))
        return

    console.print()
    manager = loader.memory_manager
    approved_count = 0
    rejected_count = 0
    skipped_count = 0

    for proposal in pending:
        mem_type = proposal.get("type", "fact")
        valence  = proposal.get("valence", "neutral")
        content  = proposal.get("content", "")
        reason   = proposal.get("reason", "")

        panel_body = (
            f"[{p.fg_faint}]Type     [{p.fg_dim}]{mem_type}[/]\n"
            f"[{p.fg_faint}]Valence  [{p.fg_dim}]{valence}[/]\n"
            f"\n"
            f"[{p.fg_em}]{content}[/]\n"
            + (f"\n[{p.fg_faint}]Reason   [{p.fg_dim}]{reason}[/]" if reason else "")
        )
        rprint(Panel(panel_body, title="memory proposal", border_style=PANEL_GATE))

        while True:
            raw = Prompt.ask(
                f"[{p.fg_dim}]Approve?[/] [{p.fg_faint}]\\[y/n/skip][/]"
            ).strip().lower()
            if raw in ("y", "n", "s", "skip"):
                break

        if raw == "y":
            result = manager.write(
                content,
                memory_type=mem_type,
                valence=valence,
                source="user_explicit",
                confidence=1.0,
            )
            proposal["status"] = "approved"
            approved_count += 1
            if result.startswith("blocked"):
                console.print(
                    f"  [{p.warn}]⚠  blocked — looks like a secret; marked approved but not written.[/]"
                )
            elif result == "duplicate":
                console.print(f"  [{p.ok}]{ICON_OK} Already in memory.[/]")
            else:
                console.print(f"  [{p.ok}]{ICON_OK} Added to memory.[/]")
        elif raw == "n":
            proposal["status"] = "rejected"
            rejected_count += 1
            console.print(f"  [{p.err}]{ICON_FAIL} Rejected.[/]")
        else:
            skipped_count += 1
            console.print(f"  [{p.fg_faint}]Skipped.[/]")

        console.print()

    proposals_path.write_text(
        "\n".join(json.dumps(entry) for entry in all_proposals) + "\n",
        encoding="utf-8",
    )

    if approved_count:
        manager._export_brain_md()

    console.print(
        f"[{p.fg_dim}]Review complete — "
        f"[/][{p.ok}]{approved_count} approved[/]"
        f"[{p.fg_dim}], [/][{p.err}]{rejected_count} rejected[/]"
        f"[{p.fg_dim}], {skipped_count} skipped.[/]"
    )


@click.group(invoke_without_command=True)
@click.pass_context
def memory(ctx: click.Context) -> None:
    """Manage agent memory."""
    if ctx.invoked_subcommand is None:
        agents = list_agents()
        if not agents:
            console.print(f"[{p.fg_faint}]no agents found. run alfard create first.[/]")
            return
        agent = alfard_select("which agent?", agents + ["← back"])
        if not agent or agent == "← back":
            return
        ctx.invoke(status, agent=agent)


@memory.command("status")
@click.argument("agent", required=False)
def status(agent: str | None = None) -> None:
    """Show memory status summary for an agent."""
    if not agent:
        agents = list_agents()
        if not agents:
            console.print(f"[{p.fg_faint}]no agents found. run alfard create first.[/]")
            return
        agent = alfard_select("which agent?", agents + ["← back"])
        if not agent or agent == "← back":
            return

    try:
        loader = AgentLoader(agent)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[{p.err}]{exc}[/]")
        return

    manager = loader.memory_manager
    proposals_path = loader.agent_dir / "memory" / "proposals.jsonl"

    # ── Counts ───────────────────────────────────────────────
    all_memories = manager.brain_db.get_all()
    active = [m for m in all_memories if m["status"] == "active"]
    active_count = len(active)

    pending_count = 0
    if proposals_path.exists():
        for line in proposals_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                if json.loads(line).get("status") == "pending":
                    pending_count += 1
            except json.JSONDecodeError:
                pass

    session_count = manager.get_session_count()

    # ── Reflect math ─────────────────────────────────────────
    last_reflect_n = (session_count // 10) * 10
    sessions_ago = session_count - last_reflect_n
    next_reflect_n = last_reflect_n + 10

    if last_reflect_n == 0:
        last_reflect_str = "—"
    else:
        plural = "s" if sessions_ago != 1 else ""
        last_reflect_str = f"Session {last_reflect_n}  ({sessions_ago} session{plural} ago)"

    # ── Summary panel ────────────────────────────────────────
    lw = 20  # plain label column width
    rows = [
        ("brain.db",        f"[{p.fg_em}]{active_count}[/] [{p.fg_dim}]active memories[/]"),
        ("proposals.jsonl", f"[{p.fg_em}]{pending_count}[/] [{p.fg_dim}]pending proposals[/]"),
        ("sessions.db",     f"[{p.fg_em}]{session_count}[/] [{p.fg_dim}]sessions recorded[/]"),
        ("last reflect",    f"[{p.fg_dim}]{last_reflect_str}[/]"),
        ("next reflect",    f"[{p.fg_dim}]Session {next_reflect_n}[/]"),
    ]
    panel_body = "\n".join(
        f"[{p.fg_faint}]{label:<{lw}}[/]{value}"
        for label, value in rows
    )
    rprint(Panel(
        panel_body,
        title=f"[{p.fg_dim}]Memory — {agent}[/]",
        border_style=PANEL_GATE,
        padding=(0, 1),
    ))

    # ── Type breakdown ───────────────────────────────────────
    by_type: dict[str, int] = {}
    for m in active:
        by_type[m["type"]] = by_type.get(m["type"], 0) + 1

    if by_type:
        console.print()
        max_count = max(by_type.values())
        ordered = [t for t in _TYPE_ORDER if t in by_type]
        ordered += [t for t in sorted(by_type) if t not in ordered]

        for mem_type in ordered:
            count = by_type[mem_type]
            bar = _build_bar(count, max_count)
            console.print(
                f"  [{p.fg_faint}]{mem_type:<16}[/]"
                f"[{p.fg_dim}]{count:>4}[/]"
                f"   {bar}"
            )
        console.print()

    # ── Pending proposals notice + inline review ─────────────
    if pending_count:
        plural = "s" if pending_count != 1 else ""
        console.print(
            f"  [{p.warn}]{pending_count} pending proposal{plural}[/]"
            f" [{p.fg_dim}]— run: alfard memory review[/]"
        )
        console.print()
        raw = Prompt.ask(
            f"  [{p.fg_dim}]Review pending proposals?[/] [{p.fg_faint}]\\[y/n][/]",
            default="n",
        ).strip().lower()
        console.print()
        if raw == "y":
            _run_review(agent, loader)


@memory.command("review")
@click.argument("agent", required=False)
def review(agent: str | None = None) -> None:
    """Review pending memory proposals for an agent.

    AGENT is the name of the agent whose proposals to review.
    """
    if not agent:
        agents = list_agents()
        if not agents:
            console.print(f"[{p.fg_faint}]no agents found. run alfard create first.[/]")
            return
        agent = alfard_select("which agent?", agents)
        if not agent:
            return

    try:
        loader = AgentLoader(agent)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[{p.err}]{exc}[/]")
        return

    _run_review(agent, loader)
