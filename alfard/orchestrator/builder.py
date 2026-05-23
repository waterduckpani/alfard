"""Orchestrator factory — shared bootstrap used by CLI and
Slack bot to avoid duplicating wiring logic."""

import shutil
from pathlib import Path

from alfard.agents.loader import AgentLoader
from alfard.llm.client import LLMClient
from alfard.tools.registry import ToolRegistry
from alfard.audit.logger import AuditLogger
from alfard.gate.approval import ApprovalGate
from alfard.sandbox.executor import SandboxExecutor
from alfard.integrations.credentials import CredentialsManager
from alfard.integrations.mcp_client import MCPClient
from alfard.orchestrator.orchestrator import Orchestrator
from alfard.commands.handlers import register_all
from alfard.memory.tools import register_memory_tools


def build_orchestrator(
    agent_name: str,
    notifier=None,
    connect_mcp: bool = True,
    gate_enabled: bool = True,
    session_id: str | None = None,
) -> tuple:
    """
    Build a fully wired orchestrator for an agent.

    Returns (orchestrator, audit, loader, registry).

    Args:
        agent_name:   Name of the agent to load.
        notifier:     Optional approval gate notifier
                      (defaults to CLINotifier).
        connect_mcp:  Whether to connect MCP servers.
        gate_enabled: Whether the approval gate is active.
    """
    loader = AgentLoader(agent_name)
    registry = ToolRegistry()
    audit = AuditLogger(session_id=session_id)

    gate = ApprovalGate(audit_logger=audit, notifier=notifier)
    gate.enabled = gate_enabled

    mcp = MCPClient(registry)
    if connect_mcp:
        mcp.connect_all()

    # gws-based tools
    gws_creds = Path.home() / ".config" / "gws" / "credentials.enc"
    if shutil.which("gws") and gws_creds.exists():
        from alfard.integrations.gws_tools import (
            register_gmail_tools, register_gdrive_tools
        )
        register_gmail_tools(registry)
        register_gdrive_tools(registry)

    # Folder mount tools
    from alfard.mounts.manager import MountManager, MountError
    from alfard.mounts.tools import register_file_tools
    try:
        mount_manager = MountManager(loader.agent_dir)
        if mount_manager.has_mounts():
            register_file_tools(registry, mount_manager)
    except MountError:
        pass

    # Web tools
    from alfard.web.config import WebConfig
    from alfard.web.tools import register_web_tools
    web_config = WebConfig(loader.agent_dir)
    if web_config.enabled:
        register_web_tools(registry, web_config)

    orchestrator = Orchestrator(
        llm=LLMClient(),
        registry=registry,
        audit=audit,
        gate=gate,
        sandbox=SandboxExecutor(),
        credentials=CredentialsManager(),
        system_prompt=loader.build_system_prompt(),
    )

    orchestrator._loader = loader
    orchestrator._agent_name = agent_name
    orchestrator._memory_manager = loader.memory_manager
    orchestrator._web_access_enabled = web_config.enabled

    register_memory_tools(registry, loader)
    register_all()

    return orchestrator, audit, loader, registry
