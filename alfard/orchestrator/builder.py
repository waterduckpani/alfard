"""Orchestrator factory — shared bootstrap used by CLI and
Slack bot to avoid duplicating wiring logic."""

import atexit
import shutil
import subprocess

from alfard.agents.loader import AgentLoader
from alfard.llm.client import LLMClient
from alfard.tools.registry import ToolRegistry
from alfard.audit.logger import AuditLogger
from alfard.gate.approval import ApprovalGate
from alfard.sandbox.executor import SandboxExecutor
from alfard.integrations.credentials import CredentialsManager
from alfard.integrations.mcp_client import MCPClient
from alfard.integrations.catalogue import CATALOGUE
from alfard.integrations.lazy_tool import (
    lazy_tool_is_available,
    LAZY_TOOL_CONFIG,
    start_lazy_tool_server,
)
from alfard.orchestrator.orchestrator import Orchestrator
from alfard.commands.handlers import register_all
from alfard.memory.tools import register_memory_tools

# Servers whose schemas are proxied through lazy-tool instead of direct connection.
_LAZY_ROUTED: frozenset[str] = frozenset(
    name for name, info in CATALOGUE.items() if info.get("routed_via_lazy_tool")
)


def _cleanup_proc(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        pass


def _connect_mcp_via_lazy_tool(mcp: MCPClient, lt_proc: subprocess.Popen) -> None:
    """Register lazy-tool as the single MCP proxy for routed servers.

    Collects the combined reversible_tools list from all routed catalogue entries so
    the approval gate still works correctly.  Non-routed servers connect directly.
    """
    reversible: list[str] = []
    for server_name in _LAZY_ROUTED:
        reversible.extend(CATALOGUE.get(server_name, {}).get("reversible_tools", []))

    lazy_cfg = {
        "name": "lazy-tool",
        "transport": "stdio",
        "command": "lazy-tool",
        "args": ["serve", "--config", str(LAZY_TOOL_CONFIG), "--transport", "stdio"],
        "env_vars": {},
        "tools": {"reversible": reversible, "irreversible": []},
    }
    print(f"[lazy-tool] connecting lazy-tool proxy with reversible_tools={reversible}")
    mcp._connect(lazy_cfg)

    direct = [cfg["name"] for cfg in mcp._server_configs if cfg["name"] not in _LAZY_ROUTED]
    print(f"[lazy-tool] connecting direct (non-routed) servers: {direct}")
    for cfg in mcp._server_configs:
        if cfg["name"] not in _LAZY_ROUTED:
            mcp._connect(cfg)

    atexit.register(_cleanup_proc, lt_proc)


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
        _lt_avail = lazy_tool_is_available()
        print(f"[lazy-tool] available={_lt_avail}")
        if _lt_avail:
            lt_proc = start_lazy_tool_server()
            print(f"[lazy-tool] process started={lt_proc is not None} pid={getattr(lt_proc, 'pid', None)}")
            if lt_proc:
                print(f"[lazy-tool] routing via lazy-tool, skipping direct: {sorted(_LAZY_ROUTED)}")
                _connect_mcp_via_lazy_tool(mcp, lt_proc)
            else:
                print("[lazy-tool] server failed to start — falling back to direct MCP")
                mcp.connect_all()
        else:
            print("[lazy-tool] not available — connecting MCP servers directly")
            mcp.connect_all()

    # gog-based tools
    from alfard.paths import ALFARD_HOME
    gog_tokens = ALFARD_HOME / "gog" / "data" / "keyring"
    if shutil.which("gog") and gog_tokens.exists():
        from alfard.integrations.gog_tools import register_gmail_tools, register_gdrive_tools
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
