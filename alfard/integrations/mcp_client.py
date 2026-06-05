"""MCP client — connects to configured MCP servers and registers their tools with the tool registry."""

import asyncio
import json
import sys
from typing import Any, TextIO

import mcp
import mcp.client.stdio
import mcp.client.streamable_http
import mcp.types
import yaml

from alfard.tools.registry import ToolRegistry
from alfard.paths import ALFARD_HOME, load_env

# Swappable stderr sink for MCP subprocess output.
# The terminal channel replaces this with a silent writer during TUI sessions
# so Node.js MCP server noise doesn't corrupt the full-screen display.
_errlog: TextIO = sys.stderr

_CONFIG_PATH = ALFARD_HOME / "config" / "integrations.yaml"


def _rank_notion_search(content: list, query: str) -> list:
    """Re-rank notion.API-post-search results for reliable database ID resolution.

    Filters archived entries, requires exact name match (case-insensitive),
    prefers database over page, then most-recently-edited. Returns content with
    an empty results list and an alfard_note if no exact match is found, so the
    agent knows to ask the user for clarification rather than using a bad ID.
    """
    if not content or not query:
        return content

    raw_text = next((b.text for b in content if hasattr(b, "text")), None)
    if raw_text is None:
        return content

    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return content

    results = data.get("results")
    if not isinstance(results, list):
        return content

    query_norm = query.strip().lower()

    def _title(r: dict) -> str:
        if r.get("object") == "database":
            return "".join(b.get("plain_text", "") for b in r.get("title", []))
        if r.get("object") == "page":
            props = r.get("properties", {})
            for prop in props.values():
                if isinstance(prop, dict) and prop.get("type") == "title":
                    return "".join(b.get("plain_text", "") for b in prop.get("title", []))
        return ""

    exact = [
        r for r in results
        if not r.get("archived", False) and _title(r).strip().lower() == query_norm
    ]

    if not exact:
        data["results"] = []
        data["alfard_note"] = (
            f"No Notion database or page named exactly '{query}' was found. "
            "Ask the user to confirm the correct name."
        )
    else:
        # Stable two-pass sort: most-recently-edited first, then databases before pages.
        exact.sort(key=lambda r: r.get("last_edited_time", ""), reverse=True)
        exact.sort(key=lambda r: 0 if r.get("object") == "database" else 1)
        data["results"] = exact

    new_text = json.dumps(data)
    new_content: list = []
    replaced = False
    for block in content:
        if not replaced and hasattr(block, "text"):
            new_content.append(mcp.types.TextContent(type="text", text=new_text))
            replaced = True
        else:
            new_content.append(block)
    return new_content


def _resolve_env_vars(env_vars: dict) -> dict:
    """Resolve env var values from environment.

    env_vars maps subprocess key -> env var name to read from os.environ.
    e.g. {"NOTION_TOKEN": "NOTION_TOKEN"} -> {"NOTION_TOKEN": "<actual token value>"}
    """
    import os
    load_env()
    resolved = {}
    for key, env_var_name in env_vars.items():
        value = os.environ.get(env_var_name, "")
        if value:
            resolved[key] = value
    return resolved


class MCPClient:

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._sessions: dict[str, Any] = {}
        self._server_configs: list[dict] = []

        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data and "servers" in data:
                self._server_configs = data["servers"]

    _MCP_TRANSPORTS = {"stdio", "http"}

    def connect_all(self) -> None:
        mcp_servers = [c for c in self._server_configs if c.get("transport") in self._MCP_TRANSPORTS]
        connected = 0
        for cfg in mcp_servers:
            self._connect(cfg)
            if cfg["name"] in self._sessions:
                connected += 1
        print(f"[mcp] connected to {connected}/{len(mcp_servers)} server(s)")

    def _connect(self, cfg: dict) -> None:
        name = cfg["name"]
        transport = cfg["transport"]
        reversible_tools: list[str] = cfg.get("tools", {}).get("reversible", [])
        irreversible_tools: list[str] = cfg.get("tools", {}).get("irreversible", [])

        def _make_transport_context():
            if transport == "http":
                return mcp.client.streamable_http.streamablehttp_client(cfg["url"])
            elif transport == "stdio":
                resolved_env = _resolve_env_vars(cfg.get("env_vars", {}))
                params = mcp.StdioServerParameters(
                    command=cfg["command"],
                    args=cfg.get("args", []),
                    # None → subprocess inherits parent env (preserves PATH, HOME, etc.)
                    # Only override when there are actual env vars to inject.
                    env=resolved_env if resolved_env else None,
                )
                import alfard.integrations.mcp_client as _self
                return mcp.client.stdio.stdio_client(params, errlog=_self._errlog)
            else:
                raise ValueError(f"Unknown transport '{transport}' for server '{name}'")

        try:
            async def _setup() -> list:
                async with _make_transport_context() as (read, write):
                    async with mcp.ClientSession(read, write) as session:
                        await session.initialize()
                        tools_result = await session.list_tools()
                        return tools_result.tools

            tools = asyncio.run(_setup())
        except Exception as exc:
            print(f"[mcp] warning: could not connect to server '{name}': {exc}")
            return

        def make_caller(server_name: str, tool_name: str):
            def caller(**kwargs):
                # Normalise notion.API-post-page: wrap bare UUID string parent
                # into the object form Notion's API requires.
                if tool_name == "API-post-page" and server_name == "notion":
                    parent = kwargs.get("parent")
                    if isinstance(parent, str):
                        kwargs["parent"] = {"database_id": parent}

                async def _call():
                    async def _inner():
                        async with _make_transport_context() as (read, write):
                            async with mcp.ClientSession(read, write) as s:
                                await s.initialize()
                                result = await s.call_tool(tool_name, kwargs)
                                content = result.content
                                if server_name == "notion" and tool_name == "API-post-search":
                                    content = _rank_notion_search(content, kwargs.get("query", ""))
                                return content
                    try:
                        return await asyncio.wait_for(_inner(), timeout=30.0)
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            f"MCP tool '{tool_name}' on server '{server_name}' "
                            f"timed out after 30 seconds"
                        )
                return asyncio.run(_call())
            return caller

        for tool in tools:
            # Blacklist mode: if irreversible_tools is provided, everything NOT
            # in that list is reversible (used by lazy-tool proxy so its own
            # meta-tools are correctly classified without enumerating them).
            # Whitelist mode (legacy): tool must be explicitly in reversible_tools.
            if irreversible_tools:
                is_reversible = tool.name not in irreversible_tools
            else:
                is_reversible = tool.name in reversible_tools
            parameters = (
                tool.inputSchema
                if tool.inputSchema
                else {"type": "object", "properties": {}}
            )
            try:
                self._registry.register(
                    name=f"{name}.{tool.name}",
                    description=tool.description or "",
                    function=make_caller(name, tool.name),
                    reversible=is_reversible,
                    parameters=parameters,
                    is_mcp=True,
                )
            except ValueError as exc:
                print(f"[mcp] warning: skipping tool '{name}.{tool.name}': {exc}")

        self._sessions[name] = True

    def list_connected(self) -> list[str]:
        return list(self._sessions.keys())
