"""CLI commands for managing and running agent cron jobs."""

import re
import yaml
import click
from pathlib import Path
from rich.markdown import Markdown
from alfard.agents.loader import list_agents, AGENTS_DIR
from alfard.cron.parser import parse_schedule
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, error_block, alfard_table, alfard_input, alfard_select, alfard_confirm

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
        elif action == "view job status":
            ctx.invoke(status)
        elif action == "run scheduler":
            ctx.invoke(run)


@cron.command(name="add")
@click.argument("agent", required=False)
@click.argument("task", required=False)
@click.option("--schedule", "-s", default=None,
              help="When to run: '8am', 'every 1h', 'daily', '0 8 * * *'")
@click.option("--name", "-n", default=None,
              help="Job name (auto-generated if not set)")
def add(agent: str | None, task: str | None,
        schedule: str | None, name: str | None):
    """Add a scheduled job to an agent."""

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
        agent = alfard_select("which agent?", agents, default=agents[0]) or agents[0]
    else:
        if agent not in list_agents():
            console.print(error_block(
                agent="alfard cron",
                state="failed",
                headline=f"agent '{agent}' not found.",
                explanation="",
            ))
            raise SystemExit(1)

    if not task:
        task = alfard_input(
            f"what should {agent} do?",
            hint="e.g. summarise my inbox from the last 24 hours",
        ).strip()
        if not task:
            console.print(f"  [{p.err}]task cannot be empty.[/]")
            raise SystemExit(1)

    if not schedule:
        schedule = alfard_input(
            "when should this run?",
            hint="e.g. 8am · every 2h · daily · 0 8 * * *",
        ).strip()
        if not schedule:
            console.print(f"  [{p.err}]schedule cannot be empty.[/]")
            raise SystemExit(1)

    try:
        parse_schedule(schedule)
    except ValueError as e:
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=str(e),
            explanation="",
        ))
        raise SystemExit(1)

    if not name:
        name = _slug(task)

    jobs = _load_crons(agent)
    if any(j["name"] == name for j in jobs):
        console.print(error_block(
            agent="alfard cron",
            state="failed",
            headline=f"job '{name}' already exists.",
            explanation=f"remove it first: alfard cron remove {agent} {name}",
        ))
        raise SystemExit(1)

    jobs.append({"name": name, "task": task, "schedule": schedule, "enabled": True})
    _save_crons(agent, jobs)

    console.print(f"\n{dot('ok')} [{p.fg_dim}]job added.[/]\n")
    console.print(f"  [{p.fg_faint}]{'agent':<10}[/] [{p.fg_em}]{agent}[/]")
    console.print(f"  [{p.fg_faint}]{'task':<10}[/] [{p.fg_em}]{task}[/]")
    console.print(f"  [{p.fg_faint}]{'schedule':<10}[/] [{p.fg_em}]{schedule}[/]")
    console.print(f"  [{p.fg_faint}]{'name':<10}[/] [{p.fg_em}]{name}[/]")
    console.print(f"\n[{p.fg_faint}]start scheduler: alfard cron run[/]")


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
            continue
        any_jobs = True
        console.print(f"\n[{p.fg_dim}]scheduled jobs — {ag}[/]")
        rows = []
        for j in jobs:
            enabled_str = (
                c("ok", "yes") if j.get("enabled", True) else c("fg_faint", "no")
            )
            task_str = j.get("task", "")
            if len(task_str) > 55:
                task_str = task_str[:52] + "..."
            rows.append({
                "name": j["name"],
                "schedule": j.get("schedule", ""),
                "enabled": enabled_str,
                "task": task_str,
            })
        console.print(alfard_table(
            [
                {"header": "name", "key": "name"},
                {"header": "schedule", "key": "schedule"},
                {"header": "enabled", "key": "enabled"},
                {"header": "task", "key": "task"},
            ],
            rows,
        ))
    if not any_jobs:
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
