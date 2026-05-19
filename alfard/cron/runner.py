"""Cron job runner — executes a scheduled agent task in an isolated
session with no human present. Approval gate is disabled."""

import shutil
import yaml
from pathlib import Path
from datetime import datetime

from alfard.agents.loader import AgentLoader, AGENTS_DIR
from alfard.llm.client import LLMClient
from alfard.tools.registry import ToolRegistry
from alfard.audit.logger import AuditLogger
from alfard.gate.approval import ApprovalGate
from alfard.sandbox.executor import SandboxExecutor
from alfard.integrations.credentials import CredentialsManager
from alfard.integrations.mcp_client import MCPClient
from alfard.orchestrator.orchestrator import Orchestrator


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
    try:
        loader = AgentLoader(agent_name)
        task = _inject_skills(loader.agent_dir, agent_name, job_name, task)
        registry = ToolRegistry()

        gate = ApprovalGate(audit_logger=audit)
        gate.enabled = False  # no human present in scheduled runs

        mcp = MCPClient(registry)
        mcp.connect_all()

        gws_creds = Path.home() / ".config" / "gws" / "credentials.enc"
        if shutil.which("gws") and gws_creds.exists():
            from alfard.integrations.gws_tools import register_gmail_tools
            register_gmail_tools(registry)

        orchestrator = Orchestrator(
            llm=LLMClient(),
            registry=registry,
            audit=audit,
            gate=gate,
            sandbox=SandboxExecutor(),
            credentials=CredentialsManager(),
            system_prompt=loader.build_system_prompt(),
        )

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
