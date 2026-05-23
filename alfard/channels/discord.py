"""Discord channel — wraps AlfardDiscordBot as a BaseChannel."""

from alfard.channels.base import BaseChannel


class DiscordChannel(BaseChannel):
    """Connects the agent to Discord via a gateway bot."""

    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name
        self._bot = None

    def get_name(self) -> str:
        return "discord"

    def start(self) -> None:
        from alfard.interfaces.discord_bot import AlfardDiscordBot
        self._bot = AlfardDiscordBot(agent_name=self._agent_name)
        self._bot.run_bot()

    def stop(self) -> None:
        if self._bot is not None:
            self._bot.stop()

    def notify_memory_write(self, entry: dict) -> None:
        # Discord notifications are sent by AlfardDiscordBot._process_message()
        # after the response is sent, where the channel object is available.
        pass
