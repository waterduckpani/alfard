"""Deterministic MCP infrastructure tools.

Replaces semantic discovery (search_tools) with structured deterministic access:
  mcp_list_sources → mcp_list_tools → lazy-tool.invoke_proxy_tool

The LLM never needs to infer namespaces, guess tool names, or run semantic searches
to discover MCP capabilities. All discovery is resolved from the local catalogue.
"""

from __future__ import annotations

import json
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


def list_tools(source: str) -> str:
    """Return all tool names for a given source from the catalogue."""
    from alfard.integrations.catalogue import CATALOGUE
    entry = CATALOGUE.get(source)
    if entry is None:
        known = sorted(CATALOGUE.keys())
        return json.dumps({
            "error": f"Unknown source '{source}'.",
            "known_sources": known,
        })
    reversible = entry.get("reversible_tools", [])
    irreversible = entry.get("irreversible_tools", [])
    return json.dumps({
        "source": source,
        "reversible_tools": reversible,
        "irreversible_tools": irreversible,
        "note": (
            "Use lazy-tool.invoke_proxy_tool(source=SOURCE, tool=TOOL, arguments={...}) "
            "to call any of these tools."
        ),
    })


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
            "List all available tool names for a connected MCP source. "
            "Returns reversible_tools (read-only) and irreversible_tools (write/delete). "
            "Use this instead of lazy-tool.search_tools — it is deterministic and instant."
        ),
        function=list_tools,
        reversible=True,
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
