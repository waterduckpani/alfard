"""Slack channel — wraps AlfardSlackBot as a BaseChannel."""

from alfard.channels.base import BaseChannel


class SlackChannel(BaseChannel):
    """Connects the agent to Slack via Socket Mode."""

    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name
        self._bot = None

    def get_name(self) -> str:
        return "slack"

    def start(self) -> None:
        from alfard.interfaces.slack_bot import AlfardSlackBot
        self._bot = AlfardSlackBot(agent_name=self._agent_name)
        self._bot.start()

    def stop(self) -> None:
        if self._bot is None:
            return
        self._bot._stop_event.set()
        try:
            self._bot.socket_client.close()
        except Exception:
            pass

    def notify_memory_write(self, entry: dict) -> None:
        # Slack notifications are posted by AlfardSlackBot._handle_message()
        # after the response is sent, where the Slack channel ID is available.
        pass
