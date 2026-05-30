"""Slack approval gate notifier — sends approval requests as
interactive Slack messages with Approve/Reject buttons."""

import logging
import os
import threading
from slack_sdk import WebClient
from alfard.cli import theme

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
        import json
        import uuid

        action_id = str(uuid.uuid4())
        event = threading.Event()
        with self._lock:
            self._pending[action_id] = event

        source_emoji = "🟢" if source == "user_instruction" else "🔴"
        args_text = json.dumps(arguments, indent=2)
        if len(args_text) > 2900:
            _log.warning(
                "gate args truncated for tool=%s action=%s original_len=%d",
                tool_name, action_id, len(args_text),
            )
            args_text = args_text[:2900] + "\n... (truncated)"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Review required*\n\n"
                            f"*Tool:* `{tool_name}`\n"
                            f"*Source:* {source_emoji} `{source}`"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Arguments:*\n```{args_text}```"
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

        self.client.chat_postMessage(
            channel=self.channel,
            text=f"Review required: {tool_name}",
            blocks=blocks
        )

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
