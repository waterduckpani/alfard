"""CLI commands for managing and running agent cron jobs."""

import re
import yaml
import click
from pathlib import Path
from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from alfard.agents.loader import list_agents, AgentLoader, AGENTS_DIR
from alfard.cron.parser import parse_schedule
from alfard.cli.theme import p, c, console, capabilities
from alfard.cli.components import (
    dot, error_block, alfard_table,
    alfard_input, alfard_select, alfard_multiselect, alfard_confirm,
)

CRONS_FILE = "crons.yaml"


def _load_crons(agent: str) -> list[dict]:
    path = AGENTS_DIR / agent / CRONS_FILE
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("jobs", [])


def _save_crons(agent: str, jobs: list[dict]) -> None:
    path = AGENTS_DIR / agent / CRONS_FILE
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump({"jobs": jobs}, f, default_flow_style=False, allow_unicode=True)


def _slug(text: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower().strip())
    slug = slug.strip("_")
    return slug[:max_len] or "job"


def _last_run(agent: str, job_name: str) -> tuple[str, str]:
    log_dir = AGENTS_DIR / agent / "cron_logs"
    if not log_dir.exists():
        return "—", "—"
    files = sorted(log_dir.glob(f"{job_name}_*.md"), reverse=True)
    if not files:
        return "—", "—"
    fname = files[0].name
    status = "error" if "_ERROR" in fname else "ok"
    m = re.search(r"_(\d{8}_\d{6})", fname)
    ts = m.group(1).replace("_", " ") if m else "?"
    return ts, status


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse '8am', '14:30', '9:30pm' → (hour, minute). Raises ValueError on bad input."""
    s = time_str.strip().lower()
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
    if not m:
        raise ValueError(f"unrecognised time: {time_str!r}. Try '8am' or '14:30'.")
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    meridiem = m.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time value: {time_str!r}")
    return hour, minute


_DOW = {
    "Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4,
    "Friday": 5, "Saturday": 6, "Sunday": 0,
}


def _collect_schedule() -> str | None:
    """Interactive schedule picker. Returns a 5-field cron expression or None if cancelled."""
    schedule_type = alfard_select("when should this run?", [
        "every few hours",
        "daily",
        "weekly",
        "advanced",
    ])
    if not schedule_type:
        return None

    if schedule_type == "every few hours":
        choice = alfard_select("how often?", ["1h", "2h", "4h", "6h", "12h"])
        if not choice:
            return None
        n = int(choice.rstrip("h"))
        return f"0 */{n} * * *"

    if schedule_type == "daily":
        time_str = alfard_input("what time?", hint="e.g. 8am · 14:30").strip()
        if not time_str:
            return None
        try:
            hour, minute = _parse_time(time_str)
        except ValueError as e:
            console.print(f"  [{p.err}]{e}[/]")
            return None
        return f"{minute} {hour} * * *"

    if schedule_type == "weekly":
        day = alfard_select("which day?", list(_DOW.keys()))
        if not day:
            return None
        time_str = alfard_input("what time?", hint="e.g. 8am · 14:30").strip()
        if not time_str:
            return None
        try:
            hour, minute = _parse_time(time_str)
        except ValueError as e:
            console.print(f"  [{p.err}]{e}[/]")
            return None
        return f"{minute} {hour} * * {_DOW[day]}"

    # advanced
    expr = alfard_input("cron expression", hint="e.g. 0 8 * * * · 30 9 * * 1-5").strip()
    if not expr:
        return None
    try:
        parse_schedule(expr)
    except ValueError as e:
        console.print(f"  [{p.err}]{e}[/]")
        return None
    return expr


def _set_enabled(agent: str, name: str, enabled: bool) -> None:
    if agent not in list_agents():
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)
    jobs = _load_crons(agent)
    found = False
    for j in jobs:
        if j["name"] == name:
            j["enabled"] = enabled
            found = True
            break
    if not found:
        console.print(f"  [{p.warn}]no job named '{name}' found for {agent}.[/]")
        return
    _save_crons(agent, jobs)
    word = "enabled" if enabled else "disabled"
    console.print(f"{dot('ok')} [{p.fg_dim}]job '{name}' {word}.[/]")


@click.group(invoke_without_command=True)
@click.pass_context
def cron(ctx: click.Context):
    """Manage and run scheduled agent jobs.

    \b
    Examples:
      alfard cron add postman "Check inbox" --schedule "8am"
      alfard cron list postman
      alfard cron status
      alfard cron run
    """
    if ctx.invoked_subcommand is not None:
        return

    import questionary

    while True:
        console.clear()
        console.print(f"\n[{p.fg_em}]manage cron jobs[/]\n")
        action = alfard_select("what would you like to do?", [
            "list jobs",
            "add a job",
            "remove a job",
            "view job status",
            "run scheduler",
            questionary.Separator(),
            "← back",
        ])
        if not action or action == "← back":
            return

        if action == "list jobs":
            ctx.invoke(list_jobs)
        elif action == "add a job":
            ctx.invoke(add)
        elif action == "remove a job":
            agents_with_jobs = [a for a in list_agents() if _load_crons(a)]
            if not agents_with_jobs:
                console.print(f"[{p.fg_faint}]no scheduled jobs found.[/]")
                alfard_input("press enter to continue", default="")
            else:
                agent = (
                    alfard_select("which agent?", agents_with_jobs)
                    if len(agents_with_jobs) > 1
                    else agents_with_jobs[0]
                )
                if agent:
                    while True:
                        jobs = _load_crons(agent)
                        if not jobs:
                            break
                        name = alfard_select(
                            "which job to remove?",
                            [j["name"] for j in jobs] + ["← done"],
                        )
                        if not name or name == "← done":
                            break
                        if not alfard_confirm(f"remove '{name}'?", default=False):
                            console.print(f"[{p.fg_faint}]cancelled.[/]")
                            continue
                        _save_crons(agent, [j for j in jobs if j["name"] != name])
                        console.print(f"{dot('ok')} [{p.fg_dim}]removed '{name}' from {agent}.[/]")
            continue
        elif action == "view job status":
            ctx.invoke(status)
        elif action == "run scheduler":
            ctx.invoke(run)
            continue
        alfard_input("press enter to continue", default="")


@cron.command(name="add")
@click.argument("agent", required=False)
def add(agent: str | None):
    """Add a scheduled job to an agent."""

    # Step 1: Agent
    agents = list_agents()
    if not agents:
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline="no agents found.",
            explanation="create one first: alfard create",
        ))
        raise SystemExit(1)
    if not agent:
        agent = alfard_select("which agent?", agents, default=agents[0]) or agents[0]
    elif agent not in agents:
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)

    # Step 2: Job name
    job_name_raw = alfard_input(
        "job name",
        hint="e.g. morning inbox summary",
    ).strip()
    if not job_name_raw:
        console.print(f"  [{p.err}]job name cannot be empty.[/]")
        raise SystemExit(1)
    name = _slug(job_name_raw)

    jobs = _load_crons(agent)
    if any(j["name"] == name for j in jobs):
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=f"job '{name}' already exists.",
            explanation=f"remove it first: alfard cron remove {agent} {name}",
        ))
        raise SystemExit(1)

    # Step 3: Task
    task = alfard_input(
        "describe the task in detail",
        hint="what to fetch, what to do with it, and what the output should be",
    ).strip()
    if not task:
        console.print(f"  [{p.err}]task cannot be empty.[/]")
        raise SystemExit(1)

    # Step 4: Skills (optional)
    loader = AgentLoader(agent)
    available_skills = loader.get_agent_skills()
    linked_skills: list[str] = []
    if available_skills:
        linked_skills = alfard_multiselect(
            "which skills should this job use? (optional — space to toggle, enter to confirm)",
            available_skills,
        )

    # Step 5: Approval
    channel_choice = alfard_select(
        "where should approval requests be sent?",
        ["telegram", "slack", "none", "disable gate"],
    )
    if channel_choice is None:
        console.print(f"[{p.fg_faint}]cancelled.[/]")
        return

    gate_disabled = False
    approval_channel = channel_choice if channel_choice != "disable gate" else "none"

    if channel_choice == "disable gate":
        console.print()
        console.print(f"  [{p.warn}]WARNING: with the gate disabled this job will execute[/]")
        console.print(f"  [{p.warn}]irreversible actions without any confirmation.[/]")
        console.print(f"  [{p.fg_faint}]CRON_ALWAYS_GATE tools (send_email, delete_file, push_code,[/]")
        console.print(f"  [{p.fg_faint}]etc.) are still denied unconditionally.[/]\n")
        confirm_text = alfard_input(
            "type 'I understand' to disable the gate",
            hint="or press enter to keep it enabled",
        ).strip()
        if confirm_text == "I understand":
            gate_disabled = True
        else:
            console.print(f"  [{p.fg_faint}]gate kept enabled — using 'none' (deny all irreversible).[/]")
            approval_channel = "none"

    # Step 6: Schedule
    cron_expr = _collect_schedule()
    if not cron_expr:
        console.print(f"[{p.fg_faint}]cancelled.[/]")
        return

    # Step 7: Confirm
    console.print()
    console.print(f"  [{p.fg_faint}]{'name':<12}[/] [{p.fg_em}]{name}[/]")
    console.print(f"  [{p.fg_faint}]{'task':<12}[/] [{p.fg_em}]{task}[/]")
    if linked_skills:
        console.print(f"  [{p.fg_faint}]{'skills':<12}[/] [{p.fg_em}]{', '.join(linked_skills)}[/]")
    if gate_disabled:
        console.print(
            f"  [{p.fg_faint}]{'approval':<12}[/] [{p.warn}]gate disabled[/]"
            f" [{p.fg_faint}](CRON_ALWAYS_GATE still enforced)[/]"
        )
    else:
        console.print(f"  [{p.fg_faint}]{'approval':<12}[/] [{p.fg_em}]{approval_channel}[/]")
    console.print(f"  [{p.fg_faint}]{'schedule':<12}[/] [{p.fg_em}]{cron_expr}[/]")
    console.print()

    if not alfard_confirm("add this job?"):
        console.print(f"[{p.fg_faint}]cancelled.[/]")
        return

    job: dict = {
        "name": name,
        "task": task,
        "schedule": cron_expr,
        "linked_skills": linked_skills,
        "enabled": True,
        "approval_channel": approval_channel,
    }
    if gate_disabled:
        job["approval_gate"] = "disabled"
    jobs.append(job)
    _save_crons(agent, jobs)
    console.print(f"\n{dot('ok')} [{p.fg_dim}]job added.[/]")
    from alfard.cli.cmd_service import _is_installed
    if _is_installed(agent):
        console.print(f"[{p.fg_faint}]cron job will run automatically — your agent is running as a service.[/]")
    else:
        console.print(f"[{p.fg_faint}]start scheduler: alfard cron run[/]")


@cron.command(name="remove")
@click.argument("agent", required=False)
@click.argument("name", required=False)
def remove(agent: str | None, name: str | None):
    """Remove a scheduled job from an agent."""
    if not agent:
        agents = list_agents()
        if not agents:
            console.print(error_block(
                agent="alfard cron",
                state="failed",
                headline="no agents found.",
                explanation="create one first: alfard create",
            ))
            raise SystemExit(1)
        agent = alfard_select("which agent?", agents)
        if not agent:
            return
    if agent not in list_agents():
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)
    jobs = _load_crons(agent)
    if not name:
        job_names = [j["name"] for j in jobs]
        if not job_names:
            console.print(f"[{p.fg_faint}]{agent} has no scheduled jobs.[/]")
            return
        name = alfard_select("which job to remove?", job_names)
        if not name:
            return
    new_jobs = [j for j in jobs if j["name"] != name]
    if len(new_jobs) == len(jobs):
        console.print(f"  [{p.warn}]no job named '{name}' found for {agent}.[/]")
        return
    _save_crons(agent, new_jobs)
    console.print(f"{dot('ok')} [{p.fg_dim}]removed job '{name}' from {agent}.[/]")


def _pick_agent_and_job(cmd: str) -> tuple[str, str] | tuple[None, None]:
    agents = list_agents()
    if not agents:
        console.print(error_block(
            agent=f"alfard cron {cmd}",
            state="failed",
            headline="no agents found.",
            explanation="create one first: alfard create",
        ))
        return None, None
    agent = alfard_select("which agent?", agents)
    if not agent:
        return None, None
    jobs = _load_crons(agent)
    job_names = [j["name"] for j in jobs]
    if not job_names:
        console.print(f"[{p.fg_faint}]{agent} has no scheduled jobs.[/]")
        return None, None
    name = alfard_select("which job?", job_names)
    return agent, name


@cron.command(name="enable")
@click.argument("agent", required=False)
@click.argument("name", required=False)
def enable(agent: str | None, name: str | None):
    """Enable a scheduled job."""
    if not agent or not name:
        agent, name = _pick_agent_and_job("enable")
        if not agent or not name:
            return
    _set_enabled(agent, name, True)


@cron.command(name="disable")
@click.argument("agent", required=False)
@click.argument("name", required=False)
def disable(agent: str | None, name: str | None):
    """Disable a scheduled job (keeps it in crons.yaml)."""
    if not agent or not name:
        agent, name = _pick_agent_and_job("disable")
        if not agent or not name:
            return
    _set_enabled(agent, name, False)


@cron.command(name="list")
@click.argument("agent", required=False)
def list_jobs(agent: str | None):
    """List scheduled jobs for one agent or all agents."""
    border = p.rule if capabilities.truecolor else "dim"
    all_agents = list_agents()
    if agent and agent not in all_agents:
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)
    targets = [agent] if agent else all_agents
    any_jobs = False

    for ag in targets:
        jobs = _load_crons(ag)

        if not jobs:
            if agent:
                content: Table | Text = Text.from_markup(
                    f"[{p.fg_faint}]no jobs. add one: alfard cron add {ag} <task>[/]"
                )
                console.print(Panel(content, title=f"[{p.fg_dim}]{ag}[/]",
                                    box=box.ROUNDED, border_style=border, padding=(0, 1)))
            continue

        any_jobs = True
        tbl = Table(box=None, show_header=False, padding=(0, 1), expand=False)
        tbl.add_column(no_wrap=True)
        tbl.add_column(no_wrap=True)
        tbl.add_column(no_wrap=True)

        for j in jobs:
            enabled = j.get("enabled", True)
            status_dot = dot("ok") if enabled else dot("queued")
            name_markup = c("fg_em", j["name"]) if enabled else c("fg_faint", j["name"])
            tbl.add_row(
                Text.from_markup(status_dot),
                Text.from_markup(name_markup),
                Text.from_markup(c("fg_dim", j.get("schedule", ""))),
            )

        console.print(Panel(tbl, title=f"[{p.fg_dim}]{ag}[/]",
                            box=box.ROUNDED, border_style=border, padding=(0, 1)))

    if not any_jobs and not agent:
        console.print(
            f"[{p.fg_dim}]no scheduled jobs found.[/]\n"
            f"[{p.fg_faint}]add one: alfard cron add <agent> <task> --schedule <when>[/]"
        )


@cron.command(name="status")
def status():
    """Show status of all scheduled jobs across all agents."""
    rows = []
    for ag in list_agents():
        for j in _load_crons(ag):
            enabled_str = (
                c("ok", "yes") if j.get("enabled", True) else c("fg_faint", "no")
            )
            ts, run_status = _last_run(ag, j["name"])
            if run_status == "error":
                last_str = c("err", f"{ts} (error)")
            elif run_status == "ok":
                last_str = c("ok", ts)
            else:
                last_str = c("fg_faint", ts)
            rows.append({
                "agent": ag,
                "name": j["name"],
                "schedule": j.get("schedule", ""),
                "enabled": enabled_str,
                "last_run": last_str,
            })
    if not rows:
        console.print(f"[{p.fg_dim}]no scheduled jobs found.[/]")
        return
    console.print(alfard_table(
        [
            {"header": "agent", "key": "agent"},
            {"header": "name", "key": "name"},
            {"header": "schedule", "key": "schedule"},
            {"header": "enabled", "key": "enabled"},
            {"header": "last run", "key": "last_run"},
        ],
        rows,
    ))


@cron.command(name="runs")
@click.argument("agent", required=False)
@click.argument("name", required=False)
@click.option("--last", default=10, show_default=True, help="Number of recent runs to show")
def runs(agent: str | None, name: str | None, last: int):
    """Show run history for a specific job."""
    if not agent or not name:
        picked_agent, picked_name = _pick_agent_and_job("runs")
        if not picked_agent or not picked_name:
            return
        agent = picked_agent
        name = picked_name
    if agent not in list_agents():
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)
    log_dir = AGENTS_DIR / agent / "cron_logs"
    if not log_dir.exists():
        console.print(f"[{p.fg_dim}]no run logs found for {agent}/{name}.[/]")
        return
    files = sorted(log_dir.glob(f"{name}_*.md"), reverse=True)[:last]
    if not files:
        console.print(f"[{p.fg_dim}]no run logs found for job '{name}' in {agent}.[/]")
        return
    rows = []
    for f in files:
        is_error = "_ERROR" in f.name
        m = re.search(r"_(\d{8}_\d{6})", f.name)
        ts = m.group(1).replace("_", " ") if m else "?"
        status_str = c("err", "error") if is_error else c("ok", "ok")
        rows.append({"timestamp": ts, "status": status_str, "file": f.name})
    console.print(f"\n[{p.fg_dim}]run history — {agent}/{name} (last {last})[/]")
    console.print(alfard_table(
        [
            {"header": "timestamp", "key": "timestamp"},
            {"header": "status", "key": "status"},
            {"header": "file", "key": "file"},
        ],
        rows,
    ))


@cron.command(name="now")
@click.argument("agent", required=False)
@click.argument("name", required=False)
def now(agent: str | None, name: str | None):
    """Run a specific scheduled job immediately."""
    if not agent or not name:
        picked_agent, picked_name = _pick_agent_and_job("now")
        if not picked_agent or not picked_name:
            return
        agent = picked_agent
        name = picked_name
    if agent not in list_agents():
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)
    jobs = _load_crons(agent)
    job = next((j for j in jobs if j["name"] == name), None)
    if job is None:
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=f"no job named '{name}' found for {agent}.",
            explanation="",
        ))
        raise SystemExit(1)
    console.print(f"[{p.fg_dim}]running '{name}' for {agent}...[/]")
    from alfard.cron.runner import run_job
    response = run_job(agent, job["task"], name)
    console.print(Markdown(response))


@cron.command(name="run")
@click.option("--background", is_flag=True, default=False, help="Run scheduler in background")
def run(background: bool):
    """Start the cron scheduler."""
    from alfard.cron.scheduler import start
    start(background=background)
    if not background:
        console.print(f"[{p.fg_dim}]scheduler stopped.[/]")
