"""Telegram channel — wraps AlfardTelegramBot as a BaseChannel."""

import asyncio
import html
import os

from alfard.channels.base import BaseChannel
from alfard.paths import load_env


class TelegramChannel(BaseChannel):
    """Connects the agent to Telegram via long polling."""

    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name
        self._bot = None

    def get_name(self) -> str:
        return "telegram"

    def start(self) -> None:
        import logging
        import traceback
        _log = logging.getLogger("alfard.telegram")
        try:
            from alfard.interfaces.telegram_bot import AlfardTelegramBot
            self._bot = AlfardTelegramBot(agent_name=self._agent_name)
            self._bot.start()
        except Exception as exc:
            _log.error(
                "telegram channel fatal error: %s\n%s", exc, traceback.format_exc()
            )
            raise

    def stop(self) -> None:
        if self._bot is not None:
            self._bot.stop()

    def notify_memory_write(self, entry: dict) -> None:
        # Telegram notifications are posted by AlfardTelegramBot._process_message()
        # after the response is sent, where the chat_id is available.
        pass

    def send_admin_message(self, text: str) -> bool:
        load_env()
        chat_id_str = os.environ.get("TELEGRAM_CRON_CHAT_ID")
        if not chat_id_str:
            raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
            parts = [u for u in raw.split(",") if u.strip().lstrip("-").isdigit()]
            chat_id_str = parts[0].strip() if parts else None
        if not chat_id_str:
            return False
        try:
            return self._send_telegram_message(int(chat_id_str), text) is not None
        except Exception:
            return False

    def post_cron_output(
        self,
        agent_name: str,
        job_name: str,
        run_ts: str,
        task: str,
        output: str,
        status: str = "completed",
    ) -> str | None:
        from alfard.cron import run_registry

        load_env()

        chat_id_str = os.environ.get("TELEGRAM_CRON_CHAT_ID")
        if not chat_id_str:
            raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
            parts = [u for u in raw.split(",") if u.strip().lstrip("-").isdigit()]
            chat_id_str = parts[0].strip() if parts else None
        if not chat_id_str:
            return None

        chat_id = int(chat_id_str)
        body = (output[:3500] + "…") if len(output) > 3500 else output
        text = f"<b>{html.escape(job_name)}</b>\n\n{html.escape(body)}"

        msg = self._send_telegram_message(chat_id, text, parse_mode="HTML")
        if msg is None:
            return None

        message_id = str(msg.message_id)
        run_registry.register_run(
            job_name=job_name,
            agent_name=agent_name,
            run_ts=run_ts,
            channel="telegram",
            message_id=message_id,
            task=task,
            thread_id=None,
            status=status,
        )
        return message_id

    def _send_telegram_message(self, chat_id: int, text: str, parse_mode: str | None = None):
        """Send a Telegram message, using the running bot loop if available."""
        if self._bot is not None and self._bot._loop is not None:
            async def _send():
                return await self._bot._app.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode=parse_mode
                )
            try:
                return asyncio.run_coroutine_threadsafe(
                    _send(), self._bot._loop
                ).result(timeout=30)
            except Exception:
                return None

        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return None

        from telegram import Bot

        async def _send_fresh():
            bot = Bot(token)
            await bot.initialize()
            try:
                return await bot.send_message(
                    chat_id=chat_id, text=text, parse_mode=parse_mode
                )
            finally:
                await bot.shutdown()

        try:
            return asyncio.run(_send_fresh())
        except Exception:
            return None

    def get_cron_run_from_event(self, event: dict) -> dict | None:
        from alfard.cron import run_registry

        mid = event.get("reply_to_message_id")
        if not mid:
            return None
        return run_registry.lookup_run("telegram", str(mid))
