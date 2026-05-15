"""Tool registry — central store for all registered tools; enforces minimum-permission access control."""


class ToolRegistry:

    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}

    def register(
        self,
        name: str,
        description: str,
        function: callable,
        reversible: bool,
        parameters: dict,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = {
            "name": name,
            "description": description,
            "function": function,
            "reversible": reversible,
            "parameters": parameters,
        }

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
        ]

    def all_tools(self) -> list[dict]:
        return list(self._tools.values())
