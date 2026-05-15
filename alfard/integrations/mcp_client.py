"""MCP client — connects to configured MCP servers and registers their tools with the tool registry."""

import asyncio
import pathlib
from typing import Any

import mcp
import mcp.client.stdio
import mcp.client.streamable_http
import yaml

from alfard.tools.registry import ToolRegistry

_CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "integrations.yaml"


class MCPClient:

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._sessions: dict[str, Any] = {}
        self._server_configs: list[dict] = []

        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH) as f:
                data = yaml.safe_load(f)
            if data and "servers" in data:
                self._server_configs = data["servers"]

    def connect_all(self) -> None:
        connected = 0
        for cfg in self._server_configs:
            self._connect(cfg)
            if cfg["name"] in self._sessions:
                connected += 1
        print(f"[mcp] connected to {connected}/{len(self._server_configs)} server(s)")

    def _connect(self, cfg: dict) -> None:
        name = cfg["name"]
        transport = cfg["transport"]
        reversible_tools: list[str] = cfg.get("tools", {}).get("reversible", [])

        def _make_transport_context():
            if transport == "http":
                return mcp.client.streamable_http.streamablehttp_client(cfg["url"])
            elif transport == "stdio":
                params = mcp.StdioServerParameters(
                    command=cfg["command"],
                    args=cfg.get("args", []),
                    env=cfg.get("env_vars", {}),
                )
                return mcp.client.stdio.stdio_client(params)
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
                async def _call():
                    async with _make_transport_context() as (read, write):
                        async with mcp.ClientSession(read, write) as s:
                            await s.initialize()
                            result = await s.call_tool(tool_name, kwargs)
                            return result.content
                return asyncio.run(_call())
            return caller

        for tool in tools:
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
                )
            except ValueError as exc:
                print(f"[mcp] warning: skipping tool '{name}.{tool.name}': {exc}")

        self._sessions[name] = True

    def list_connected(self) -> list[str]:
        return list(self._sessions.keys())
