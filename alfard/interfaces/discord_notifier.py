"""Discord approval gate notifier — sends an embed with Approve/Reject buttons and
blocks until the user clicks one."""

import asyncio
import json
import threading
import uuid

import discord


class _ApprovalView(discord.ui.View):
    """Ephemeral view with Approve / Reject buttons for a single gate request."""

    def __init__(self, notifier: "DiscordNotifier", action_id: str) -> None:
        super().__init__(timeout=300)
        self._notifier = notifier
        self._action_id = action_id

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._notifier.resolve(self._action_id, True)
        self.stop()
        await interaction.response.edit_message(content="✅ Approved", embed=None, view=None)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._notifier.resolve(self._action_id, False)
        self.stop()
        await interaction.response.edit_message(content="❌ Rejected", embed=None, view=None)


class DiscordNotifier:
    """Blocks orchestrator execution until the Discord user clicks an approval button."""

    def __init__(self, channel: discord.abc.Messageable, loop: asyncio.AbstractEventLoop) -> None:
        self._channel = channel
        self._loop = loop
        self._pending: dict[str, threading.Event] = {}
        self._decisions: dict[str, bool] = {}
        self._lock = threading.Lock()

    def present(self, tool_name: str, arguments: dict, source: str) -> str:
        action_id = str(uuid.uuid4())[:8]
        event = threading.Event()
        with self._lock:
            self._pending[action_id] = event

        source_emoji = "🟢" if source == "user_instruction" else "🔴"
        args_text = json.dumps(arguments, indent=2)[:900]

        embed = discord.Embed(title="Review required", color=0x5865F2)
        embed.add_field(name="Tool", value=f"`{tool_name}`", inline=True)
        embed.add_field(name="Source", value=f"{source_emoji} `{source}`", inline=True)
        embed.add_field(
            name="Arguments", value=f"```json\n{args_text}\n```", inline=False
        )

        view = _ApprovalView(self, action_id)
        future = asyncio.run_coroutine_threadsafe(
            self._channel.send(embed=embed, view=view),
            self._loop,
        )
        try:
            future.result(timeout=10)
        except Exception:
            pass

        event.wait(timeout=300)

        with self._lock:
            decision = self._decisions.pop(action_id, None)
            self._pending.pop(action_id, None)

        return "y" if decision else "n"

    def resolve(self, action_id: str, approved: bool) -> None:
        """Called when an approval button is clicked."""
        with self._lock:
            if action_id in self._pending:
                self._decisions[action_id] = approved
                self._pending[action_id].set()
