"""Approval gate — intercepts irreversible tool calls and waits for explicit human confirmation before allowing execution."""

import json
import pathlib
import yaml
from rich.panel import Panel
from rich.prompt import Prompt
from rich import print as rprint
from alfard.cli import theme

_CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "alfard.yaml"


class CLINotifier:

    def present(self, tool_name: str, arguments: dict, source: str) -> str:
        content = (
            f"[dim]Tool:       {tool_name}\n"
            f"Arguments:  {json.dumps(arguments, indent=2)}\n"
            f"Source:     {source}[/dim]"
        )
        rprint(Panel(content, title="Review required", border_style=theme.PANEL_GATE))
        while True:
            choice = Prompt.ask("Approve? [dim]\\[y/n][/dim]").strip().lower()
            if choice in ("y", "n"):
                return choice


class ApprovalGate:

    def __init__(self, audit_logger=None) -> None:
        self.audit_logger = audit_logger
        self._notifier = CLINotifier()
        self.enabled = True
        try:
            with open(_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f) or {}
            self.enabled = cfg.get("approval_gate", {}).get("enabled", True)
        except FileNotFoundError:
            pass

    def request(self, tool_name: str, arguments: dict, source: str) -> bool:
        if not self.enabled:
            return True
        choice = self._notifier.present(tool_name, arguments, source)
        result = choice == "y"
        if self.audit_logger is not None:
            self.audit_logger.log_gate_decision(
                tool_name,
                arguments,
                decision="approved" if result else "rejected",
                source=source,
            )
        return result
