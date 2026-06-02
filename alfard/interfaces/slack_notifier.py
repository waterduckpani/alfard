"""Slack approval gate notifier — sends approval requests as
interactive Slack messages with Approve/Reject buttons."""

import logging
import os
import threading
from slack_sdk import WebClient
from alfard.cli import theme
from alfard.gate.formatter import action_summary, human_label

_log = logging.getLogger("alfard.slack")

class SlackNotifier:
    """
    Sends approval gate requests to Slack as interactive Block Kit
    messages. Waits for the user to click Approve or Reject.
    Uses a threading.Event to block until the button is clicked.
    """

    def __init__(self, web_client: WebClient, channel: str):
        self.client = web_client
        self.channel = channel
        self._pending: dict[str, threading.Event] = {}
        self._decisions: dict[str, bool] = {}
        self._lock = threading.Lock()

    def present(self, tool_name: str, arguments: dict,
                source: str) -> str:
        """
        Send an interactive approval message to Slack and block
        until the user clicks Approve or Reject.
        Returns "y" or "n".
        """
        import uuid

        action_id = str(uuid.uuid4())
        event = threading.Event()
        with self._lock:
            self._pending[action_id] = event

        source_emoji = "🟢" if source == "user_instruction" else "🔴"
        summary = action_summary(tool_name, arguments)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Review required*\n\n"
                            f"*Tool:* `{human_label(tool_name, arguments)}`\n"
                            f"*Source:* {source_emoji} `{source}`"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Action:* {summary}"
                }
            },
            {
                "type": "actions",
                "block_id": action_id,
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text",
                                 "text": "✅  Approve"},
                        "style": "primary",
                        "value": "approved",
                        "action_id": f"{action_id}_approve"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text",
                                 "text": "❌  Reject"},
                        "style": "danger",
                        "value": "rejected",
                        "action_id": f"{action_id}_reject"
                    }
                ]
            }
        ]

        try:
            self.client.chat_postMessage(
                channel=self.channel,
                text=f"Review required: {tool_name}",
                blocks=blocks
            )
        except Exception as exc:
            _log.error(
                "gate_send_failure: could not send approval request for action=%s tool=%s: %s",
                action_id, tool_name, exc,
            )
            with self._lock:
                self._pending.pop(action_id, None)
            try:
                self.client.chat_postMessage(
                    channel=self.channel,
                    text=f"⚠️ Could not deliver approval request for `{tool_name}` — action auto-rejected.",
                )
            except Exception:
                pass
            return "n"

        # Block until button clicked (timeout 5 minutes)
        event.wait(timeout=300)

        if action_id not in self._decisions:
            # Timed out — default reject
            self._cleanup(action_id)
            return "n"

        decision = self._decisions.pop(action_id)
        self._cleanup(action_id)
        return "y" if decision else "n"

    def resolve(self, action_id: str, approved: bool) -> None:
        """Called by the bot when a button is clicked."""
        with self._lock:
            if action_id in self._pending:
                self._decisions[action_id] = approved
                self._pending[action_id].set()

    def _cleanup(self, action_id: str) -> None:
        with self._lock:
            self._pending.pop(action_id, None)
