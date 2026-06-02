"""Telegram approval gate notifier — sends gate requests as inline keyboard
messages and blocks until the user taps Approve or Reject."""

import asyncio
import html
import logging
import threading
import uuid

from alfard.gate.formatter import action_summary, human_label

_log = logging.getLogger("alfard.telegram")


class TelegramNotifier:
    """Blocks orchestrator execution until the Telegram user taps an approval button."""

    def __init__(self, bot, chat_id: int, loop: asyncio.AbstractEventLoop) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._loop = loop
        self._pending: dict[str, threading.Event] = {}
        self._decisions: dict[str, bool] = {}
        self._lock = threading.Lock()

    def present(self, tool_name: str, arguments: dict, source: str) -> str:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        action_id = str(uuid.uuid4())[:8]
        event = threading.Event()
        with self._lock:
            self._pending[action_id] = event

        source_emoji = "🟢" if source == "user_instruction" else "🔴"
        summary = html.escape(action_summary(tool_name, arguments))
        text = (
            f"<b>Review required</b>\n\n"
            f"<b>Tool:</b> <code>{html.escape(human_label(tool_name, arguments))}</code>\n"
            f"<b>Source:</b> {source_emoji} <code>{html.escape(source)}</code>\n\n"
            f"{summary}"
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"gate:{action_id}:approve"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"gate:{action_id}:reject"),
        ]])

        future = asyncio.run_coroutine_threadsafe(
            self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            ),
            self._loop,
        )
        try:
            future.result(timeout=10)
        except Exception as exc:
            _log.error(
                "gate_send_failure: could not send approval request for action=%s tool=%s: %s",
                action_id, tool_name, exc,
                exc_info=True,
            )
            with self._lock:
                self._pending.pop(action_id, None)
            try:
                asyncio.run_coroutine_threadsafe(
                    self._bot.send_message(
                        chat_id=self._chat_id,
                        text=f"⚠️ Could not deliver approval request for `{tool_name}` — action auto-rejected.",
                    ),
                    self._loop,
                )
            except Exception:
                pass
            return "n"

        event.wait(timeout=300)

        with self._lock:
            decision = self._decisions.pop(action_id, None)
            self._pending.pop(action_id, None)

        return "y" if decision else "n"

    def resolve(self, action_id: str, approved: bool) -> None:
        """Called from the callback query handler when a button is tapped."""
        with self._lock:
            if action_id in self._pending:
                self._decisions[action_id] = approved
                self._pending[action_id].set()
