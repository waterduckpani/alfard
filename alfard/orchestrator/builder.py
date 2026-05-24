"""Orchestrator factory — shared bootstrap used by CLI and
Slack bot to avoid duplicating wiring logic."""

import shutil

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
)
from alfard.integrations.mcp_tools import register_mcp_infra_tools
from alfard.orchestrator.orchestrator import Orchestrator
from alfard.commands.handlers import register_all
from alfard.memory.tools import register_memory_tools

# Servers whose schemas are proxied through lazy-tool instead of direct connection.
_LAZY_ROUTED: frozenset[str] = frozenset(
    name for name, info in CATALOGUE.items() if info.get("routed_via_lazy_tool")
)



def _connect_mcp_via_lazy_tool(mcp: MCPClient, registry) -> None:
    """Register lazy-tool as the single MCP proxy for routed servers.

    Collects the combined irreversible_tools list from all routed catalogue entries so
    the approval gate still works correctly.  Non-routed servers connect directly.
    Records each proxied integration name in the registry for /status visibility.
    """
    irreversible: list[str] = []
    for server_name in _LAZY_ROUTED:
        irreversible.extend(CATALOGUE.get(server_name, {}).get("irreversible_tools", []))

    lazy_cfg = {
        "name": "lazy-tool",
        "transport": "stdio",
        "command": "lazy-tool",
        "args": ["serve", "--config", str(LAZY_TOOL_CONFIG), "--transport", "stdio"],
        "env_vars": {},
        "tools": {"reversible": [], "irreversible": irreversible},
    }
    mcp._connect(lazy_cfg)

    for cfg in mcp._server_configs:
        if cfg["name"] not in _LAZY_ROUTED:
            mcp._connect(cfg)

    # Mark each routed server that was actually in integrations.yaml as proxied
    # so /status can show them even though no direct MCP session exists.
    configured_names = {cfg["name"] for cfg in mcp._server_configs}
    for name in _LAZY_ROUTED:
        if name in configured_names:
            registry.register_proxied_integration(name)

    # Hide search_tools from the LLM — semantic search is not a valid MCP
    # traversal path. The model must use mcp_list_sources + mcp_list_tools instead.
    for hidden in ("lazy-tool.search_tools", "lazy-tool.list_tools", "lazy-tool.get_tool_schema"):
        if registry.is_registered(hidden):
            registry.hide(hidden)

    # Register deterministic infra tools that replace semantic discovery.
    register_mcp_infra_tools(registry)


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
        if lazy_tool_is_available():
            _connect_mcp_via_lazy_tool(mcp, registry)
        else:
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
