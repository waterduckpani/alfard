"""Cron job terminal fallback — used when no channel bot is running.

When a cron fires and no bot is registered for the configured channel,
this module builds a one-shot orchestrator with CLI approval and runs
the task directly. Used by `alfard cron now` and as a scheduler fallback.
"""

import logging
import yaml
from pathlib import Path
from datetime import datetime

from alfard.agents.loader import AGENTS_DIR
from alfard.cron.context import build_cron_context

_log = logging.getLogger("alfard.cron_runner")


def _load_job_cfg(agent_name: str, job_name: str) -> dict:
    jobs_path = AGENTS_DIR / agent_name / "crons.yaml"
    if not jobs_path.exists():
        return {}
    with open(jobs_path) as f:
        data = yaml.safe_load(f) or {}
    return next((j for j in data.get("jobs", []) if j["name"] == job_name), {})


def run_job(agent_name: str, task: str, job_name: str) -> str:
    """Run a cron job in a terminal-local one-shot session.

    Builds an orchestrator with the normal CLI approval gate so the user
    can approve irreversible actions from the terminal. CRON_ALWAYS_GATE
    tools are denied unconditionally.

    Returns the agent's response text.
    """
    audit = None
    run_ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    try:
        job_cfg = _load_job_cfg(agent_name, job_name)
        linked_skills: list[str] | None = job_cfg.get("linked_skills") or None
        gate_enabled = job_cfg.get("approval_gate") != "disabled"

        from alfard.orchestrator.builder import build_orchestrator
        from alfard.gate.cron_gate import CRON_ALWAYS_GATE
        from alfard.gate.approval import ToolDeniedError

        orchestrator, audit, loader, _registry = build_orchestrator(
            agent_name=agent_name,
            connect_mcp=True,
            gate_enabled=gate_enabled,
            linked_skills=linked_skills,
            interactive=False,
        )

        def _pre_tool_hook(tool_name: str, arguments: dict) -> None:
            if tool_name in CRON_ALWAYS_GATE:
                raise ToolDeniedError(
                    f"{tool_name} denied by CRON_ALWAYS_GATE — "
                    "this tool always requires channel approval even in fallback mode."
                )

        orchestrator.pre_tool_hook = _pre_tool_hook

        cron_text = build_cron_context(job_name, task) + "\n\n" + task
        response = orchestrator.run(cron_text)

        _save_log(loader.agent_dir, job_name, task, response, error=False)
        return response

    except Exception as exc:
        msg = f"Cron job '{job_name}' failed: {exc}"
        _log.error(msg, exc_info=True)
        try:
            _save_log(AGENTS_DIR / agent_name, job_name, task, msg, error=True)
        except Exception:
            pass
        return msg
    finally:
        if audit is not None:
            try:
                audit.close()
            except Exception:
                pass


def _save_log(
    agent_dir: Path, job_name: str, task: str, content: str, error: bool
) -> None:
    log_dir = agent_dir / "cron_logs"
    log_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "_ERROR" if error else ""
    (log_dir / f"{job_name}_{ts}{suffix}.md").write_text(
        f"# {job_name}\n**Run:** {ts}\n**Task:** {task}\n\n"
        f"## {'Error' if error else 'Response'}\n\n{content}\n",
        encoding="utf-8",
    )
