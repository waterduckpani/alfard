"""Approval gate — intercepts irreversible tool calls and waits for explicit human confirmation before allowing execution."""

import json
import threading
from typing import Callable, Optional
import yaml
from rich.panel import Panel
from rich.prompt import Prompt
from rich import print as rprint
from alfard.cli import theme
from alfard.paths import ALFARD_HOME

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"

# Kept for non-terminal (headless/service) contexts that still use CLINotifier.
_STDIN_LOCK = threading.Lock()


class CLINotifier:

    def present(self, tool_name: str, arguments: dict, source: str) -> str:
        content = (
            f"[{theme.DIM}]Tool:       {tool_name}\n"
            f"Arguments:  {json.dumps(arguments, indent=2)}\n"
            f"Source:     {source}[/{theme.DIM}]"
        )
        rprint(Panel(content, title="Review required", border_style=theme.PANEL_GATE))
        with _STDIN_LOCK:
            while True:
                choice = Prompt.ask(f"Approve? [{theme.DIM}]\\[y/n][/{theme.DIM}]").strip().lower()
                if choice in ("y", "n"):
                    return choice


class QueueNotifier:
    """Approval notifier for the async terminal loop.

    present() is called from the executor thread; it invokes the optional
    on_present callback (for UI rendering), sets the pending flag, then blocks
    until the async main loop calls post_response().
    """

    def __init__(self) -> None:
        self._pending = threading.Event()
        self._response_ready = threading.Event()
        self._response: str = "n"
        self._on_present: Optional[Callable[[str, dict, str], None]] = None

    def set_on_present(self, fn: Callable[[str, dict, str], None]) -> None:
        """Register a callback that renders the approval panel into the UI."""
        self._on_present = fn

    def has_pending(self) -> bool:
        return self._pending.is_set()

    def present(self, tool_name: str, arguments: dict, source: str) -> str:
        if self._on_present is not None:
            self._on_present(tool_name, arguments, source)
        else:
            # Fallback for non-Application contexts (e.g. headless).
            content = (
                f"[{theme.DIM}]Tool:       {tool_name}\n"
                f"Arguments:  {json.dumps(arguments, indent=2)}\n"
                f"Source:     {source}[/{theme.DIM}]"
            )
            rprint(Panel(content, title="Review required", border_style=theme.PANEL_GATE))
        self._pending.set()
        self._response_ready.wait()
        self._response_ready.clear()
        return self._response

    def post_response(self, response: str) -> None:
        """Called from the async main loop with 'y' or 'n'."""
        self._pending.clear()
        self._response = response
        self._response_ready.set()


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
        if not self.enabled:
            rprint(Panel(
                "[bold]WARNING: Approval gate is disabled. All irreversible actions will execute "
                "without confirmation. This is unsafe for production use.[/bold]",
                border_style="red",
                title="[red]Security Warning[/red]",
            ))

    def reset_job(self) -> None:
        self._job_approved = False
        self._approved_server = None

    def _integration_key(self, tool_name: str, arguments: dict) -> str:
        """Derive the scoping key for per-session approval bypass.

        Uses arguments["source"] for mcp_invoke calls so that approval is
        scoped to the specific integration (gmail, notion, …) rather than
        the generic protocol name "mcp".
        """
        if arguments.get("source"):
            return str(arguments["source"])
        return tool_name.split(".")[0] if "." in tool_name else tool_name.split("_")[0]

    def request(self, tool_name: str, arguments: dict, source: str) -> bool:
        if not self.enabled:
            return True

        if self._job_approved:
            current_server = self._integration_key(tool_name, arguments)
            if current_server == self._approved_server:
                return True
            self._job_approved = False
            self._approved_server = None

        decision = self._notifier.present(tool_name, arguments, source)
        approved = decision == "y"

        if approved:
            self._job_approved = True
            self._approved_server = self._integration_key(tool_name, arguments)

        if self.audit_logger:
            self.audit_logger.log_tool_call(
                tool_name, arguments,
                "gate_approved" if approved else "gate_rejected"
            )

        return approved
