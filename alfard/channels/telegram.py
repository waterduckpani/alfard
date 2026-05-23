"""Telegram channel — wraps AlfardTelegramBot as a BaseChannel."""

from alfard.channels.base import BaseChannel


class TelegramChannel(BaseChannel):
    """Connects the agent to Telegram via long polling."""

    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name
        self._bot = None

    def get_name(self) -> str:
        return "telegram"

    def start(self) -> None:
        from alfard.interfaces.telegram_bot import AlfardTelegramBot
        self._bot = AlfardTelegramBot(agent_name=self._agent_name)
        self._bot.start()

    def stop(self) -> None:
        if self._bot is not None:
            self._bot.stop()

    def notify_memory_write(self, entry: dict) -> None:
        # Telegram notifications are posted by AlfardTelegramBot._process_message()
        # after the response is sent, where the chat_id is available.
        pass
