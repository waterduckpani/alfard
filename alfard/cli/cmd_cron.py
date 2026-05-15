"""CLI commands for managing and running agent cron jobs."""

import re
import yaml
import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from alfard.agents.loader import list_agents, AGENTS_DIR
from alfard.cron.parser import parse_schedule
from alfard.cli import theme

console = Console()
CRONS_FILE = "crons.yaml"


def _load_crons(agent: str) -> list[dict]:
    path = AGENTS_DIR / agent / CRONS_FILE
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("jobs", [])


def _save_crons(agent: str, jobs: list[dict]) -> None:
    path = AGENTS_DIR / agent / CRONS_FILE
    with open(path, "w") as f:
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


def _set_enabled(agent: str, name: str, enabled: bool) -> None:
    if agent not in list_agents():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.ERROR
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
        console.print(f"[{theme.WARNING}]No job named '{name}' found for {agent}.[/{theme.WARNING}]")
        return
    _save_crons(agent, jobs)
    word = "enabled" if enabled else "disabled"
    icon = theme.ICON_OK if enabled else theme.ICON_FAIL
    color = theme.SUCCESS if enabled else theme.DIM
    console.print(f"[{color}]{icon} Job '{name}' {word}.[/{color}]")


@click.group()
def cron():
    """Manage and run scheduled agent jobs.

    Examples:
      alfard cron add postman "Check inbox" --schedule "8am"
      alfard cron list postman
      alfard cron status
      alfard cron run
    """
    pass


@cron.command(name="add")
@click.argument("agent")
@click.argument("task")
@click.option("--schedule", required=True, help="When to run: '8am', 'every 2h', 'daily', '0 8 * * *'")
@click.option("--name", default=None, help="Job name (auto-generated from task if omitted)")
def add(agent: str, task: str, schedule: str, name: str | None):
    """Add a scheduled job to an agent."""
    if agent not in list_agents():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.ERROR
        ))
        raise SystemExit(1)
    try:
        parse_schedule(schedule)
    except ValueError as e:
        console.print(Panel(str(e), border_style=theme.ERROR))
        raise SystemExit(1)
    job_name = name or _slug(task)
    jobs = _load_crons(agent)
    if any(j["name"] == job_name for j in jobs):
        console.print(Panel(
            f"[{theme.ERROR}]A job named '{job_name}' already exists for {agent}.[/{theme.ERROR}]\n\n"
            f"Use a different name with [bold]--name[/bold].",
            border_style=theme.ERROR
        ))
        raise SystemExit(1)
    jobs.append({"name": job_name, "task": task, "schedule": schedule, "enabled": True})
    _save_crons(agent, jobs)
    console.print(Panel(
        f"[{theme.SUCCESS}]{theme.ICON_OK} Job '{job_name}' added to {agent}.[/{theme.SUCCESS}]\n\n"
        f"[{theme.DIM}]Schedule:[/{theme.DIM}] {schedule}\n"
        f"[{theme.DIM}]Task:[/{theme.DIM}] {task}\n\n"
        f"Start the scheduler: [bold {theme.PRIMARY}]alfard cron run[/bold {theme.PRIMARY}]",
        border_style=theme.SUCCESS
    ))


@cron.command(name="remove")
@click.argument("agent")
@click.argument("name")
def remove(agent: str, name: str):
    """Remove a scheduled job from an agent."""
    if agent not in list_agents():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.ERROR
        ))
        raise SystemExit(1)
    jobs = _load_crons(agent)
    new_jobs = [j for j in jobs if j["name"] != name]
    if len(new_jobs) == len(jobs):
        console.print(f"[{theme.WARNING}]No job named '{name}' found for {agent}.[/{theme.WARNING}]")
        return
    _save_crons(agent, new_jobs)
    console.print(f"[{theme.SUCCESS}]{theme.ICON_OK} Removed job '{name}' from {agent}.[/{theme.SUCCESS}]")


@cron.command(name="enable")
@click.argument("agent")
@click.argument("name")
def enable(agent: str, name: str):
    """Enable a scheduled job."""
    _set_enabled(agent, name, True)


@cron.command(name="disable")
@click.argument("agent")
@click.argument("name")
def disable(agent: str, name: str):
    """Disable a scheduled job (keeps it in crons.yaml)."""
    _set_enabled(agent, name, False)


@cron.command(name="list")
@click.argument("agent", required=False)
def list_jobs(agent: str | None):
    """List scheduled jobs for one agent or all agents."""
    all_agents = list_agents()
    if agent and agent not in all_agents:
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.ERROR
        ))
        raise SystemExit(1)
    targets = [agent] if agent else all_agents
    any_jobs = False
    for ag in targets:
        jobs = _load_crons(ag)
        if not jobs:
            continue
        any_jobs = True
        table = Table(
            title=f"Scheduled jobs — {ag}",
            border_style=theme.BORDER,
            show_header=True
        )
        table.add_column("Name", style="bold")
        table.add_column("Schedule")
        table.add_column("Enabled")
        table.add_column("Task")
        for j in jobs:
            enabled_str = (
                f"[{theme.SUCCESS}]yes[/{theme.SUCCESS}]"
                if j.get("enabled", True)
                else f"[{theme.DIM}]no[/{theme.DIM}]"
            )
            task_str = j.get("task", "")
            if len(task_str) > 55:
                task_str = task_str[:52] + "..."
            table.add_row(j["name"], j.get("schedule", ""), enabled_str, task_str)
        console.print(table)
    if not any_jobs:
        console.print(
            f"[{theme.DIM}]No scheduled jobs found.[/{theme.DIM}]\n"
            f"Add one: [bold {theme.PRIMARY}]alfard cron add <agent> <task> --schedule <when>"
            f"[/bold {theme.PRIMARY}]"
        )


@cron.command(name="status")
def status():
    """Show status of all scheduled jobs across all agents."""
    table = Table(
        title="Cron job status",
        border_style=theme.BORDER,
        show_header=True
    )
    table.add_column("Agent", style="bold")
    table.add_column("Name")
    table.add_column("Schedule")
    table.add_column("Enabled")
    table.add_column("Last run")
    any_jobs = False
    for ag in list_agents():
        for j in _load_crons(ag):
            any_jobs = True
            enabled_str = (
                f"[{theme.SUCCESS}]yes[/{theme.SUCCESS}]"
                if j.get("enabled", True)
                else f"[{theme.DIM}]no[/{theme.DIM}]"
            )
            ts, run_status = _last_run(ag, j["name"])
            if run_status == "error":
                last_str = f"[{theme.ERROR}]{ts} (error)[/{theme.ERROR}]"
            elif run_status == "ok":
                last_str = f"[{theme.SUCCESS}]{ts}[/{theme.SUCCESS}]"
            else:
                last_str = f"[{theme.DIM}]{ts}[/{theme.DIM}]"
            table.add_row(ag, j["name"], j.get("schedule", ""), enabled_str, last_str)
    if not any_jobs:
        console.print(f"[{theme.DIM}]No scheduled jobs found.[/{theme.DIM}]")
        return
    console.print(table)


@cron.command(name="runs")
@click.argument("agent")
@click.argument("name")
@click.option("--last", default=10, show_default=True, help="Number of recent runs to show")
def runs(agent: str, name: str, last: int):
    """Show run history for a specific job."""
    if agent not in list_agents():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.ERROR
        ))
        raise SystemExit(1)
    log_dir = AGENTS_DIR / agent / "cron_logs"
    if not log_dir.exists():
        console.print(f"[{theme.DIM}]No run logs found for {agent}/{name}.[/{theme.DIM}]")
        return
    files = sorted(log_dir.glob(f"{name}_*.md"), reverse=True)[:last]
    if not files:
        console.print(f"[{theme.DIM}]No run logs found for job '{name}' in {agent}.[/{theme.DIM}]")
        return
    table = Table(
        title=f"Run history — {agent}/{name} (last {last})",
        border_style=theme.BORDER,
        show_header=True
    )
    table.add_column("Timestamp")
    table.add_column("Status")
    table.add_column("File")
    for f in files:
        is_error = "_ERROR" in f.name
        m = re.search(r"_(\d{8}_\d{6})", f.name)
        ts = m.group(1).replace("_", " ") if m else "?"
        status_str = (
            f"[{theme.ERROR}]error[/{theme.ERROR}]"
            if is_error
            else f"[{theme.SUCCESS}]ok[/{theme.SUCCESS}]"
        )
        table.add_row(ts, status_str, f.name)
    console.print(table)


@cron.command(name="now")
@click.argument("agent")
@click.argument("name")
def now(agent: str, name: str):
    """Run a specific scheduled job immediately."""
    if agent not in list_agents():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.ERROR
        ))
        raise SystemExit(1)
    jobs = _load_crons(agent)
    job = next((j for j in jobs if j["name"] == name), None)
    if job is None:
        console.print(Panel(
            f"[{theme.ERROR}]No job named '{name}' found for {agent}.[/{theme.ERROR}]",
            border_style=theme.ERROR
        ))
        raise SystemExit(1)
    console.print(f"[{theme.DIM}]Running '{name}' for {agent}…[/{theme.DIM}]")
    from alfard.cron.runner import run_job
    response = run_job(agent, job["task"], name)
    console.print(Markdown(response))


@cron.command(name="run")
@click.option("--background", is_flag=True, default=False, help="Run scheduler in background")
def run(background: bool):
    """Start the cron scheduler."""
    from alfard.cron.scheduler import start
    start(background=background)
