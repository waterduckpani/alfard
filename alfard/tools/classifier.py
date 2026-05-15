"""Tool classifier — labels a registered tool call as reversible or irreversible."""

from alfard.tools.registry import ToolRegistry

REVERSIBLE = "reversible"
IRREVERSIBLE = "irreversible"


def classify(tool_name: str, registry: ToolRegistry) -> str:
    tool = registry.get(tool_name)
    return REVERSIBLE if tool["reversible"] else IRREVERSIBLE
