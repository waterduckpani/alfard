"""Discord channel — wraps AlfardDiscordBot as a BaseChannel."""

import asyncio
import os

from alfard.channels.base import BaseChannel
from alfard.paths import load_env


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

    def post_cron_output(
        self,
        agent_name: str,
        job_name: str,
        run_ts: str,
        task: str,
        output: str,
        status: str = "completed",
    ) -> str | None:
        import discord
        from alfard.cron import run_registry

        load_env()

        if self._bot is None or self._bot._loop is None:
            return None

        channel_id_str = os.environ.get("DISCORD_CRON_CHANNEL_ID")
        if not channel_id_str:
            return None
        try:
            channel_id = int(channel_id_str)
        except ValueError:
            return None

        body = (output[:3900] + "…") if len(output) > 3900 else output
        embed = discord.Embed(
            title=job_name,
            description=body or "_no output_",
            color=0x5865F2,
        )
        embed.set_footer(text="Reply in this thread to continue")

        async def _send():
            ch = self._bot.get_channel(channel_id)
            if ch is None:
                ch = await self._bot.fetch_channel(channel_id)
            return await ch.send(embed=embed)

        try:
            msg = asyncio.run_coroutine_threadsafe(
                _send(), self._bot._loop
            ).result(timeout=30)
        except Exception:
            return None

        message_id = str(msg.id)
        run_registry.register_run(
            job_name=job_name,
            agent_name=agent_name,
            run_ts=run_ts,
            channel="discord",
            message_id=message_id,
            task=task,
            thread_id=None,
            status=status,
        )
        return message_id

    def get_cron_run_from_event(self, event: dict) -> dict | None:
        from alfard.cron import run_registry

        mid = event.get("reference_message_id")
        if not mid:
            return None
        return run_registry.lookup_run("discord", str(mid))
