"""Tool registry — central store for all registered tools; enforces minimum-permission access control."""


class ToolRegistry:

    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}
        self._proxied_integrations: set[str] = set()

    def register(
        self,
        name: str,
        description: str,
        function: callable,
        reversible: bool,
        parameters: dict,
        is_mcp: bool = False,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = {
            "name": name,
            "description": description,
            "function": function,
            "reversible": reversible,
            "parameters": parameters,
            "is_mcp": is_mcp,
            "hidden": False,
        }

    def hide(self, name: str) -> None:
        """Remove a tool from LLM-visible schemas without unregistering it.

        Hidden tools remain callable internally but the model never sees them,
        preventing accidental or hallucinated calls.
        """
        if name in self._tools:
            self._tools[name]["hidden"] = True

    def get(self, name: str) -> dict:
        if name not in self._tools:
            registered = ", ".join(sorted(self._tools)) or "<none>"
            raise ValueError(
                f"Tool '{name}' is not registered. Registered tools: {registered}"
            )
        return self._tools[name]

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    def get_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in self._tools.values()
            if not tool.get("hidden")
        ]

    def register_proxied_integration(self, name: str) -> None:
        """Record an integration name that is connected via a proxy (e.g. lazy-tool)."""
        self._proxied_integrations.add(name)

    def list_proxied_integrations(self) -> list[str]:
        return sorted(self._proxied_integrations)

    def all_tools(self) -> list[dict]:
        return list(self._tools.values())
