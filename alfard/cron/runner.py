"""Cron job runner — executes a scheduled agent task in an isolated
session with no human present."""

import logging
import os
import yaml
from pathlib import Path
from datetime import datetime

from alfard.agents.loader import AgentLoader, AGENTS_DIR
from alfard.audit.logger import AuditLogger
from alfard.gate.approval import ApprovalGate
from alfard.gate.cron_gate import CronChannelGate, CRON_ALWAYS_GATE
from alfard.orchestrator.builder import build_orchestrator

_log = logging.getLogger("alfard.cron_runner")

_CONFIG_PATH = Path.home() / ".alfard" / "config" / "alfard.yaml"

_CRON_BLOCK_MSG = (
    "Action blocked: no approval channel is configured for this cron job. "
    "Set cron.approval_channel in alfard.yaml or approval_channel on the job in crons.yaml."
)


class _CronDenyGate(ApprovalGate):
    """Fallback gate when no approval channel is configured.

    Denies every irreversible request unconditionally.
    """

    def request(self, tool_name: str, arguments: dict, source: str) -> bool:
        if self.audit_logger:
            self.audit_logger.log_tool_call(
                tool_name, arguments, f"cron_gate_denied — {_CRON_BLOCK_MSG}"
            )
        return False


class _CronPermissiveGate(ApprovalGate):
    """Gate used when cron.approval_gate is disabled.

    Auto-approves all irreversible actions except those in CRON_ALWAYS_GATE,
    which are denied unconditionally regardless of the disabled setting.
    """

    def request(self, tool_name: str, arguments: dict, source: str) -> bool:
        if tool_name in CRON_ALWAYS_GATE:
            if self.audit_logger:
                self.audit_logger.log_tool_call(
                    tool_name, arguments,
                    "cron_gate_denied — CRON_ALWAYS_GATE enforced even when approval_gate: disabled",
                )
            return False
        return True


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


def _make_telegram_notifier(cfg: dict):
    from telegram import Bot
    from alfard.interfaces.telegram_notifier import TelegramNotifier
    from alfard.paths import load_env
    import asyncio
    import threading

    load_env()
    tg = cfg.get("telegram", {})
    token_env = tg.get("bot_token_env", "TELEGRAM_BOT_TOKEN")
    token = os.environ.get(token_env)
    chat_id = tg.get("chat_id")
    if not token or not chat_id:
        _log.error(
            "telegram notifier: missing %s env var or telegram.chat_id in config",
            token_env,
        )
        return None

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    async def _init() -> Bot:
        bot = Bot(token)
        await bot.initialize()
        return bot

    try:
        bot = asyncio.run_coroutine_threadsafe(_init(), loop).result(timeout=15)
    except Exception as exc:
        _log.error("telegram notifier: bot init failed: %s", exc)
        return None

    return TelegramNotifier(bot=bot, chat_id=int(chat_id), loop=loop)


def _make_slack_notifier(cfg: dict):
    from slack_sdk import WebClient
    from alfard.interfaces.slack_notifier import SlackNotifier
    from alfard.paths import load_env

    load_env()
    sl = cfg.get("slack", {})
    token_env = sl.get("bot_token_env", "SLACK_BOT_TOKEN")
    token = os.environ.get(token_env)
    channel = sl.get("channel")
    if not token or not channel:
        _log.error(
            "slack notifier: missing %s env var or slack.channel in config",
            token_env,
        )
        return None

    return SlackNotifier(web_client=WebClient(token=token), channel=channel)


def _make_discord_notifier(cfg: dict):
    # Discord requires a connected gateway client for interactive buttons and is not
    # supported from the isolated cron runner context. Use telegram or slack instead.
    _log.error(
        "approval_channel: discord is not supported in cron runner "
        "(requires a running gateway bot) — falling back to deny"
    )
    return None


def _make_notifier(channel: str, cfg: dict):
    if channel == "telegram":
        return _make_telegram_notifier(cfg)
    if channel == "slack":
        return _make_slack_notifier(cfg)
    if channel == "discord":
        return _make_discord_notifier(cfg)
    _log.error("unknown approval_channel: %r", channel)
    return None


def _make_cron_gate(job_name: str, agent_name: str, audit: AuditLogger) -> ApprovalGate:
    """Build the appropriate gate for a cron job from config."""
    cfg = _read_cfg()
    cron_cfg = cfg.get("cron", {})
    job_cfg = _load_job_cfg(agent_name, job_name)

    gate_setting = str(
        job_cfg.get("approval_gate") or cron_cfg.get("approval_gate", "enabled")
    ).lower()
    channel = str(
        job_cfg.get("approval_channel") or cron_cfg.get("approval_channel", "none")
    ).lower()
    scheduled_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    if gate_setting == "disabled":
        audit.log_tool_call(
            "cron_approval_gate",
            {"job": job_name, "agent": agent_name},
            "gate_disabled_warning",
        )
        _log.warning(
            "cron approval gate is DISABLED for job=%s agent=%s — "
            "irreversible actions will execute without confirmation "
            "(CRON_ALWAYS_GATE tools are still denied)",
            job_name, agent_name,
        )
        return _CronPermissiveGate(audit_logger=audit)

    if channel == "none":
        return _CronDenyGate(audit_logger=audit)

    notifier = _make_notifier(channel, cfg)
    if notifier is None:
        _log.error(
            "approval_channel=%r could not be initialised for job=%s — falling back to deny",
            channel, job_name,
        )
        return _CronDenyGate(audit_logger=audit)

    return CronChannelGate(
        notifier=notifier,
        audit_logger=audit,
        job_name=job_name,
        agent_name=agent_name,
        scheduled_time=scheduled_time,
    )


def _inject_skills(agent_dir: Path, agent_name: str, job_name: str, task: str) -> str:
    """Prepend linked skill contents to the task prompt if any are configured."""
    jobs_path = agent_dir.parent / agent_name / "crons.yaml"
    if not jobs_path.exists():
        return task
    with open(jobs_path) as f:
        data = yaml.safe_load(f) or {}
    job = next((j for j in data.get("jobs", []) if j["name"] == job_name), None)
    if not job:
        return task
    linked_skills = job.get("linked_skills") or []
    if not linked_skills:
        return task
    parts = []
    for skill_name in linked_skills:
        skill_file = agent_dir / "skills" / f"{skill_name}.md"
        if skill_file.exists():
            parts.append(skill_file.read_text(encoding="utf-8").strip())
    if not parts:
        return task
    return "\n\n".join(parts) + "\n\n---\n\n" + task


def run_job(agent_name: str, task: str, job_name: str) -> str:
    audit = AuditLogger()
    log_dir = AGENTS_DIR / agent_name / "cron_logs"
    try:
        Path(log_dir / job_name).resolve().relative_to(log_dir.resolve())
    except (ValueError, OSError):
        audit.log_tool_call(
            "cron_save_log",
            {"job_name": job_name},
            "path_traversal_blocked",
        )
        audit.close()
        return f"Cron job '{job_name}': invalid job_name — log not saved."
    try:
        loader = AgentLoader(agent_name)
        task = _inject_skills(loader.agent_dir, agent_name, job_name, task)

        orchestrator, audit, loader, _registry = build_orchestrator(
            agent_name=agent_name,
            connect_mcp=True,
            gate_enabled=False,
        )

        orchestrator._gate = _make_cron_gate(job_name, agent_name, audit)

        response = orchestrator.run(task)
        _save_log(loader.agent_dir, job_name, task, response, error=False)
        return response

    except Exception as exc:
        msg = f"Cron job '{job_name}' failed: {exc}"
        try:
            _save_log(AGENTS_DIR / agent_name, job_name, task, msg, error=True)
        except Exception:
            pass
        return msg
    finally:
        try:
            audit.close()
        except Exception:
            pass

def _save_log(agent_dir: Path, job_name: str, task: str,
              content: str, error: bool) -> None:
    log_dir = agent_dir / "cron_logs"
    log_dir.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = "_ERROR" if error else ""
    (log_dir / f"{job_name}_{ts}{suffix}.md").write_text(
        f"# {job_name}\n**Run:** {ts}Z\n**Task:** {task}\n\n"
        f"## {'Error' if error else 'Response'}\n\n{content}\n",
        encoding="utf-8",
    )
