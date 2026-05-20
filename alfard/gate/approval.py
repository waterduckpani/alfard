"""Approval gate — intercepts irreversible tool calls and waits for explicit human confirmation before allowing execution."""

import json
import yaml
from rich.panel import Panel
from rich.prompt import Prompt
from rich import print as rprint
from alfard.cli import theme
from alfard.paths import ALFARD_HOME

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"


class CLINotifier:

    def present(self, tool_name: str, arguments: dict, source: str) -> str:
        content = (
            f"[{theme.DIM}]Tool:       {tool_name}\n"
            f"Arguments:  {json.dumps(arguments, indent=2)}\n"
            f"Source:     {source}[/{theme.DIM}]"
        )
        rprint(Panel(content, title="Review required", border_style=theme.PANEL_GATE))
        while True:
            choice = Prompt.ask(f"Approve? [{theme.DIM}]\\[y/n][/{theme.DIM}]").strip().lower()
            if choice in ("y", "n"):
                return choice


class ApprovalGate:

    def __init__(self, audit_logger=None, notifier=None) -> None:
        self.audit_logger = audit_logger
        self._notifier = notifier if notifier is not None else CLINotifier()
        self.enabled = True
        self._job_approved = False  # approved for current job
        self._approved_server = None  # which server was approved
        try:
            with open(_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f) or {}
            self.enabled = cfg.get("approval_gate", {}).get("enabled", True)
        except FileNotFoundError:
            pass

    def reset_job(self) -> None:
        self._job_approved = False
        self._approved_server = None

    def request(self, tool_name: str, arguments: dict, source: str) -> bool:
        if not self.enabled:
            return True

        if self._job_approved:
            current_server = tool_name.split(".")[0] if "." in tool_name else tool_name.split("_")[0]
            if current_server == self._approved_server:
                return True
            self._job_approved = False
            self._approved_server = None

        decision = self._notifier.present(tool_name, arguments, source)
        approved = decision == "y"

        if approved:
            self._job_approved = True
            self._approved_server = tool_name.split(".")[0] if "." in tool_name else tool_name.split("_")[0]

        if self.audit_logger:
            self.audit_logger.log_tool_call(
                tool_name, arguments,
                "gate_approved" if approved else "gate_rejected"
            )

        return approved
