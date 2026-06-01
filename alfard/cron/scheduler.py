"""Cron scheduler — loads agent jobs and fires them on schedule.

When a job fires, it is injected into the running bot for the configured
channel via bot_registry. If no bot is running, it falls back to the
terminal runner (one-shot orchestrator with CLI approval).

On every start, all stale jobs are purged and crons.yaml is the sole
source of truth. A background watcher thread re-registers jobs within
30 seconds of any crons.yaml change while the scheduler is running.
"""

import logging
import threading
import yaml
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from tzlocal import get_localzone

from alfard.agents.loader import AGENTS_DIR, list_agents
from alfard.cron.parser import parse_schedule
from alfard.paths import ALFARD_HOME

CRON_DB = ALFARD_HOME / "logs" / "cron_jobs.sqlite"
CRONS_FILE = "crons.yaml"

_log = logging.getLogger("alfard.cron_scheduler")
_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"


def _read_cfg() -> dict:
    try:
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _load_job_cfg(agent_name: str, job_name: str) -> dict:
    jobs_path = AGENTS_DIR / agent_name / "crons.yaml"
    if not jobs_path.exists():
        return {}
    with open(jobs_path) as f:
        data = yaml.safe_load(f) or {}
    return next((j for j in data.get("jobs", []) if j["name"] == job_name), {})


def _fire_cron_job(agent_name: str, job_name: str, task: str) -> str | None:
    """Fire a cron job — inject into the running bot, or fall back to terminal runner.

    Returns the response string when using the terminal fallback (so callers
    can print it), or None when routed through a channel bot.
    """
    job_cfg = _load_job_cfg(agent_name, job_name)
    cfg = _read_cfg()
    cron_cfg = cfg.get("cron", {})

    channel_name = str(
        job_cfg.get("approval_channel") or cron_cfg.get("approval_channel") or ""
    ).strip().lower()

    bot = None
    if channel_name:
        from alfard.cron.bot_registry import get_bot
        bot = get_bot(agent_name, channel_name)

    if bot is not None:
        try:
            bot.inject_cron_message(job_cfg, job_name, task)
        except Exception as exc:
            _log.error(
                "inject_cron_message failed job=%s agent=%s channel=%s: %s",
                job_name, agent_name, channel_name, exc, exc_info=True,
            )
        return None

    # No bot running — fall back to one-shot terminal runner.
    _log.info(
        "no bot registered for agent=%s channel=%s — using terminal fallback for job=%s",
        agent_name, channel_name or "(none)", job_name,
    )
    from alfard.cron.runner import run_job
    return run_job(agent_name, task, job_name)


def _make_scheduler(background: bool = False):
    CRON_DB.parent.mkdir(parents=True, exist_ok=True)
    jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{CRON_DB}")}
    cls = BackgroundScheduler if background else BlockingScheduler
    return cls(jobstores=jobstores, timezone=get_localzone())


def load_agent_crons(scheduler, agent_name: str) -> int:
    """Register all enabled jobs from agent_name/crons.yaml into scheduler.

    Caller is responsible for removing existing jobs for this agent first
    if doing a reload.
    """
    path = AGENTS_DIR / agent_name / CRONS_FILE
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    count = 0
    for job in data.get("jobs", []):
        if not job.get("enabled", True):
            continue
        job_id = f"{agent_name}.{job['name']}"
        try:
            parsed = parse_schedule(job["schedule"])
        except ValueError as e:
            print(f"[cron] skipping '{job_id}': {e}")
            continue
        tz_name = job.get("timezone")
        tz = ZoneInfo(tz_name) if tz_name else get_localzone()
        trigger = (
            CronTrigger(**parsed["kwargs"], timezone=tz)
            if parsed["trigger"] == "cron"
            else IntervalTrigger(**parsed["kwargs"])
        )
        scheduler.add_job(
            _fire_cron_job,
            trigger=trigger,
            id=job_id,
            name=f"{agent_name}: {job['name']}",
            args=[agent_name, job["name"], job["task"]],
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        count += 1
    return count


def _reload_agent_jobs(scheduler, agent_name: str) -> None:
    """Remove all scheduled jobs for agent_name and re-register from crons.yaml."""
    for job in scheduler.get_jobs():
        if job.id.startswith(f"{agent_name}."):
            try:
                scheduler.remove_job(job.id)
            except Exception:
                pass
    n = load_agent_crons(scheduler, agent_name)
    _log.info("reloaded %d job(s) for agent '%s' (crons.yaml changed)", n, agent_name)
    print(f"[cron] reloaded {n} job(s) for '{agent_name}' (crons.yaml updated)", flush=True)


def _watch_crons(scheduler, stop_event: threading.Event) -> None:
    """Background thread: poll every 30 s and reload any agent whose crons.yaml changed."""
    mtimes: dict[str, float] = {}

    for agent in list_agents():
        path = AGENTS_DIR / agent / CRONS_FILE
        mtimes[agent] = path.stat().st_mtime if path.exists() else 0.0

    while not stop_event.wait(30):
        for agent in list_agents():
            path = AGENTS_DIR / agent / CRONS_FILE
            mtime = path.stat().st_mtime if path.exists() else 0.0
            if mtime != mtimes.get(agent, -1.0):
                mtimes[agent] = mtime
                try:
                    _reload_agent_jobs(scheduler, agent)
                except Exception as exc:
                    _log.error(
                        "cron watcher: reload failed for agent=%s: %s",
                        agent, exc, exc_info=True,
                    )


def start(background: bool = False) -> None:
    scheduler = _make_scheduler(background)

    # Purge all jobs persisted from previous runs.
    # crons.yaml is the sole source of truth — the SQLite store is a runtime cache only.
    scheduler.remove_all_jobs()

    total = 0
    for agent in list_agents():
        n = load_agent_crons(scheduler, agent)
        if n > 0:
            print(f"[cron] {n} job(s) loaded for '{agent}'")
        total += n

    if total == 0:
        print("[cron] no jobs found. Add one: alfard cron add <agent> <task> --schedule <when>")
        return

    print(f"[cron] scheduler starting with {total} job(s) — Ctrl+C to stop")

    stop_event = threading.Event()
    threading.Thread(
        target=_watch_crons,
        args=(scheduler, stop_event),
        daemon=True,
        name="alfard-cron-watcher",
    ).start()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        stop_event.set()
        print("[cron] stopped.")
