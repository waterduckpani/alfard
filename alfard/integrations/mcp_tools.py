"""Deterministic MCP infrastructure tools.

Replaces semantic discovery and proxy-name guessing with structured deterministic access:
  mcp_list_sources → mcp_list_tools → mcp_invoke

The LLM never constructs proxy names, infers namespaces, or calls invoke_proxy_tool.
All MCP routing is resolved internally by the runtime.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alfard.tools.registry import ToolRegistry


def _make_list_sources(registry: "ToolRegistry"):
    def list_sources() -> str:
        """Return the connected MCP integration sources."""
        sources = registry.list_proxied_integrations()
        if not sources:
            return json.dumps({"sources": [], "note": "No MCP integrations are currently connected."})
        return json.dumps({"sources": sources})
    return list_sources


def _flatten_exc(exc: BaseException) -> str:
    """Recursively unwrap ExceptionGroup to expose actual leaf error messages."""
    if hasattr(exc, "exceptions"):
        parts = [_flatten_exc(e) for e in exc.exceptions]  # type: ignore[attr-defined]
        return " | ".join(parts)
    return f"{type(exc).__name__}: {exc}"


def list_tools(source: str) -> str:
    """Return actual tool names for a source by querying the live MCP server.

    Falls back to the catalogue if the server cannot be reached.
    This ensures tool names are always accurate regardless of server version.
    """
    import mcp
    import mcp.client.stdio
    import alfard.integrations.mcp_client as _mcp_mod
    from alfard.integrations.catalogue import CATALOGUE
    from alfard.paths import load_env

    entry = CATALOGUE.get(source)
    if entry is None:
        return json.dumps({
            "error": f"Unknown source '{source}'.",
            "known_sources": sorted(CATALOGUE.keys()),
        })

    transport = entry.get("mcp_transport", "stdio")
    catalogue_reversible = entry.get("reversible_tools", [])
    catalogue_irreversible = entry.get("irreversible_tools", [])
    note = "Use mcp_invoke(source=SOURCE, tool=TOOL, arguments={...}) to call any of these tools."

    if transport != "stdio":
        return json.dumps({
            "source": source,
            "reversible_tools": catalogue_reversible,
            "irreversible_tools": catalogue_irreversible,
            "note": note,
        })

    credential_env = entry.get("credential_env", "")
    mcp_env_var = entry.get("mcp_env_var", credential_env)
    load_env()
    env: dict[str, str] | None = None
    if credential_env:
        token = os.environ.get(credential_env, "")
        if token:
            env = {mcp_env_var: token}

    known_irreversible = set(catalogue_irreversible)

    async def _fetch():
        params = mcp.StdioServerParameters(
            command=entry["mcp_command"],
            args=entry.get("mcp_args", []),
            env=env,
        )
        async with mcp.client.stdio.stdio_client(params, errlog=_mcp_mod._errlog) as (read, write):
            async with mcp.ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    try:
        tools = asyncio.run(_fetch())
        reversible = [t.name for t in tools if t.name not in known_irreversible]
        irreversible = [t.name for t in tools if t.name in known_irreversible]
        return json.dumps({
            "source": source,
            "reversible_tools": reversible,
            "irreversible_tools": irreversible,
            "note": note,
        })
    except BaseException as exc:
        return json.dumps({
            "source": source,
            "reversible_tools": catalogue_reversible,
            "irreversible_tools": catalogue_irreversible,
            "note": note,
            "warning": f"Live query failed ({_flatten_exc(exc)}); showing catalogue defaults — actual names may differ.",
        })


def _direct_mcp_call(source: str, tool: str, arguments: dict, entry: dict) -> str:
    """Spawn a direct MCP connection to the source server and invoke the tool.

    Bypasses lazy-tool entirely — the runtime resolves all routing internally.
    Only supports stdio transport; gog/oauth transports return a clear error.
    """
    import mcp
    import mcp.client.stdio
    import alfard.integrations.mcp_client as _mcp_mod
    from alfard.integrations.mcp_client import _rank_notion_search
    from alfard.paths import load_env

    transport = entry.get("mcp_transport", "stdio")
    if transport != "stdio":
        return json.dumps({
            "error": (
                f"Direct invoke requires stdio transport; '{source}' uses '{transport}'. "
                "This integration is not yet supported via mcp_invoke."
            )
        })

    command = entry["mcp_command"]
    args = entry.get("mcp_args", [])
    credential_env = entry.get("credential_env", "")
    # Some integrations expose a different env var name to the MCP subprocess.
    mcp_env_var = entry.get("mcp_env_var", credential_env)

    load_env()
    env: dict[str, str] | None = None
    if credential_env:
        token = os.environ.get(credential_env, "")
        if token:
            env = {mcp_env_var: token}

    # Normalize Notion API-post-page: wrap bare UUID string parent into object form.
    if tool == "API-post-page" and source == "notion":
        parent = arguments.get("parent")
        if isinstance(parent, str):
            arguments = dict(arguments, parent={"database_id": parent})

    async def _call():
        params = mcp.StdioServerParameters(command=command, args=args, env=env)
        async with mcp.client.stdio.stdio_client(params, errlog=_mcp_mod._errlog) as (read, write):
            async with mcp.ClientSession(read, write) as session:
                await session.initialize()
                try:
                    result = await asyncio.wait_for(
                        session.call_tool(tool, arguments),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError(
                        f"Tool '{tool}' on '{source}' timed out after 30 seconds"
                    )
                content = result.content
                if source == "notion" and tool == "API-post-search":
                    content = _rank_notion_search(content, arguments.get("query", ""))
                return content

    try:
        result = asyncio.run(_call())
        return str(result)
    except BaseException as exc:
        return json.dumps({"error": _flatten_exc(exc)})


def _make_invoke(registry: "ToolRegistry"):
    def mcp_invoke(source: str, tool: str, arguments: dict | None = None) -> str:
        """Invoke an MCP tool by source and tool name. Never construct proxy names."""
        from alfard.integrations.catalogue import CATALOGUE

        if arguments is None:
            arguments = {}

        entry = CATALOGUE.get(source)
        if entry is None:
            return json.dumps({
                "error": f"Unknown source '{source}'.",
                "known_sources": sorted(CATALOGUE.keys()),
            })

        all_tools = entry.get("reversible_tools", []) + entry.get("irreversible_tools", [])
        if tool not in all_tools:
            return json.dumps({
                "error": f"Unknown tool '{tool}' for source '{source}'.",
                "available_tools": all_tools,
            })

        # Fast path: tool already registered in registry as "{source}.{tool}".
        registered_name = f"{source}.{tool}"
        if registry.is_registered(registered_name):
            tool_entry = registry.get(registered_name)
            try:
                result = tool_entry["function"](**arguments)
                return str(result)
            except Exception as exc:
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

        # Slow path: spawn a direct MCP connection to the source server.
        return _direct_mcp_call(source, tool, arguments, entry)

    return mcp_invoke


def _make_get_schema(registry: "ToolRegistry"):
    def mcp_get_schema(source: str, tool: str) -> str:
        """Return the input schema for an MCP tool without invoking it."""
        from alfard.integrations.catalogue import CATALOGUE
        import mcp
        import mcp.client.stdio
        import alfard.integrations.mcp_client as _mcp_mod
        from alfard.paths import load_env

        entry = CATALOGUE.get(source)
        if entry is None:
            return json.dumps({
                "error": f"Unknown source '{source}'.",
                "known_sources": sorted(CATALOGUE.keys()),
            })

        all_tools = entry.get("reversible_tools", []) + entry.get("irreversible_tools", [])
        if tool not in all_tools:
            return json.dumps({
                "error": f"Unknown tool '{tool}' for source '{source}'.",
                "available_tools": all_tools,
            })

        # Check registry first.
        registered_name = f"{source}.{tool}"
        if registry.is_registered(registered_name):
            tool_entry = registry.get(registered_name)
            return json.dumps({
                "source": source,
                "tool": tool,
                "schema": tool_entry.get("parameters", {}),
            })

        transport = entry.get("mcp_transport", "stdio")
        if transport != "stdio":
            return json.dumps({"error": f"Schema lookup requires stdio transport; '{source}' uses '{transport}'."})

        credential_env = entry.get("credential_env", "")
        mcp_env_var = entry.get("mcp_env_var", credential_env)
        load_env()
        env: dict[str, str] | None = None
        if credential_env:
            token = os.environ.get(credential_env, "")
            if token:
                env = {mcp_env_var: token}

        async def _fetch():
            params = mcp.StdioServerParameters(
                command=entry["mcp_command"],
                args=entry.get("mcp_args", []),
                env=env,
            )
            async with mcp.client.stdio.stdio_client(params, errlog=_mcp_mod._errlog) as (read, write):
                async with mcp.ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    for t in tools_result.tools:
                        if t.name == tool:
                            return t.inputSchema or {}
            return None

        try:
            schema = asyncio.run(_fetch())
            if schema is None:
                return json.dumps({"error": f"Tool '{tool}' not found on server '{source}'."})
            return json.dumps({"source": source, "tool": tool, "schema": schema})
        except Exception as exc:
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    return mcp_get_schema


def register_mcp_infra_tools(registry: "ToolRegistry") -> None:
    """Register deterministic MCP infrastructure tools into the registry.

    Call this after lazy-tool has been connected so that list_sources
    reflects the actual connected integrations.
    """
    registry.register(
        name="mcp_list_sources",
        description=(
            "List all connected MCP integration sources (e.g. notion, github). "
            "Call this first when the user's request involves an external integration "
            "and you need to confirm which sources are available."
        ),
        function=_make_list_sources(registry),
        reversible=True,
        parameters={"type": "object", "properties": {}},
    )

    registry.register(
        name="mcp_list_tools",
        description=(
            "List all available tool names for a connected MCP source by querying the live server. "
            "Returns reversible_tools (read-only) and irreversible_tools (write/delete). "
            "Always call this before mcp_invoke to get accurate tool names."
        ),
        function=list_tools,
        reversible=True,
        is_mcp=True,  # Spawns an MCP subprocess — must bypass the sandbox.
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Integration source name, e.g. 'notion' or 'github'.",
                }
            },
            "required": ["source"],
        },
    )

    registry.register(
        name="mcp_invoke",
        description=(
            "Invoke any MCP tool by source and tool name. "
            "Always call mcp_list_tools first to confirm the exact tool name. "
            "Never construct proxy names or call invoke_proxy_tool directly. "
            "Example: mcp_invoke(source='notion', tool='API-post-search', arguments={'query': 'Tasks'})"
        ),
        function=_make_invoke(registry),
        reversible=True,  # Reversibility is re-evaluated per-call in the orchestrator.
        is_mcp=True,  # Closure + async internals — must bypass the sandbox.
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Integration source name, e.g. 'notion' or 'github'.",
                },
                "tool": {
                    "type": "string",
                    "description": "Exact tool name as returned by mcp_list_tools.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Tool arguments as a JSON object. Use mcp_get_schema to see required fields.",
                },
            },
            "required": ["source", "tool"],
        },
    )

    registry.register(
        name="mcp_get_schema",
        description=(
            "Return the input schema for a specific MCP tool. "
            "Call this when you need to know the required arguments before invoking a tool."
        ),
        function=_make_get_schema(registry),
        reversible=True,
        is_mcp=True,  # Closure + async internals — must bypass the sandbox.
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Integration source name.",
                },
                "tool": {
                    "type": "string",
                    "description": "Exact tool name as returned by mcp_list_tools.",
                },
            },
            "required": ["source", "tool"],
        },
    )
