"""Cron scheduler — loads agent jobs and runs them on schedule
using APScheduler with SQLite persistence."""

import yaml
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from tzlocal import get_localzone
from alfard.agents.loader import AGENTS_DIR, list_agents
from alfard.cron.parser import parse_schedule
from alfard.cron.runner import run_job
from alfard.paths import ALFARD_HOME

CRON_DB = ALFARD_HOME / "logs" / "cron_jobs.sqlite"
CRONS_FILE = "crons.yaml"

def _make_scheduler(background=False):
    CRON_DB.parent.mkdir(parents=True, exist_ok=True)
    jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{CRON_DB}")}
    cls = BackgroundScheduler if background else BlockingScheduler
    return cls(jobstores=jobstores, timezone=get_localzone())

def load_agent_crons(scheduler, agent_name: str) -> int:
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
        trigger = (CronTrigger(**parsed["kwargs"], timezone=get_localzone())
                   if parsed["trigger"] == "cron"
                   else IntervalTrigger(**parsed["kwargs"]))
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
        scheduler.add_job(
            run_job, trigger=trigger, id=job_id,
            name=f"{agent_name}: {job['name']}",
            args=[agent_name, job["task"], job["name"]],
            replace_existing=True, max_instances=1,
            coalesce=True, misfire_grace_time=3600,
        )
        count += 1
    return count

def start(background=False):
    scheduler = _make_scheduler(background)
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
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("[cron] stopped.")
