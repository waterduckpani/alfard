"""Cron approval gate — routes irreversible tool calls from scheduled jobs through
a channel notifier (Telegram, Discord, or Slack) with a 1800-second timeout."""

import asyncio
import json
import logging
import threading
import uuid

import discord

_log = logging.getLogger("alfard.cron_gate")

_TIMEOUT = 1800  # 30 minutes

# ---------------------------------------------------------------------------
# Tool lists
# ---------------------------------------------------------------------------

# Tools that must always reach the gate in cron, even if they are classified as
# reversible or a standing session approval exists for the integration.
# Imported and enforced by the cron runner, not by this gate internally.
CRON_ALWAYS_GATE: set[str] = {
    # Gmail — mutations
    "create_draft",
    "label_message",
    "label_thread",
    "unlabel_message",
    "unlabel_thread",
    "create_label",
    "update_label",
    "delete_label",
    # Google Drive — writes
    "create_file",
    "copy_file",
    # General destructive / side-effecting
    "send_email",
    "send_message",
    "post_message",
    "delete_file",
    "delete_message",
    "delete_thread",
    "create_pull_request",
    "push_code",
    "execute_code",
    "run_script",
}


# ---------------------------------------------------------------------------
# Discord approval view
# ---------------------------------------------------------------------------

class _CronApprovalView(discord.ui.View):
    """Discord Approve / Reject buttons for a single cron gate request."""

    def __init__(self, gate: "CronChannelGate", action_id: str, owner_id: int) -> None:
        super().__init__(timeout=_TIMEOUT)
        self._gate = gate
        self._action_id = action_id
        self.owner_id = owner_id
        self._message: discord.Message | None = None

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        self._gate.resolve(self._action_id, True)
        self.stop()
        await interaction.response.edit_message(content="✅ Approved", embed=None, view=None)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Not authorised.", ephemeral=True)
            return
        self._gate.resolve(self._action_id, False)
        self.stop()
        await interaction.response.edit_message(content="❌ Rejected", embed=None, view=None)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self._message is not None:
            try:
                embed = discord.Embed(
                    title="Cron approval required",
                    description="⏱ Timed out — action rejected",
                    color=0x5865F2,
                )
                await self._message.edit(embed=embed, view=self)
            except Exception:
                pass
        self._gate.resolve(self._action_id, False)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class CronChannelGate:
    """Approval gate for cron-scheduled jobs.

    Sends approval requests through a channel notifier (Telegram, Discord, or
    Slack) and blocks for up to 1800 seconds awaiting a human response. Tools
    """

    def __init__(
        self,
        notifier,
        audit_logger=None,
        *,
        job_name: str = "unknown",
        agent_name: str = "unknown",
        scheduled_time: str = "",
    ) -> None:
        self._notifier = notifier
        self.audit_logger = audit_logger
        self._job_name = job_name
        self._agent_name = agent_name
        self._scheduled_time = scheduled_time
        self._pending: dict[str, threading.Event] = {}
        self._decisions: dict[str, bool] = {}
        self._lock = threading.Lock()

    def request(self, tool_name: str, arguments: dict, source: str) -> bool:
        """Gate an irreversible tool call from a scheduled cron job.

        Returns True if approved, False if rejected or timed out.
        """
        action_id = str(uuid.uuid4())[:8]
        event = threading.Event()
        with self._lock:
            self._pending[action_id] = event

        sent = self._send(action_id, tool_name, arguments, source)
        if not sent:
            with self._lock:
                self._pending.pop(action_id, None)
            _log.error(
                "gate_send_failure: could not deliver cron approval request "
                "action=%s tool=%s — auto-rejected",
                action_id, tool_name,
            )
            if self.audit_logger:
                self.audit_logger.log_tool_call(tool_name, arguments, "gate_rejected")
            return False

        responded = event.wait(timeout=_TIMEOUT)

        with self._lock:
            decision = self._decisions.pop(action_id, None)
            self._pending.pop(action_id, None)

        if not responded or decision is None:
            _log.warning(
                "gate_timeout: cron gate timed out after %ds "
                "action=%s tool=%s job=%s",
                _TIMEOUT, action_id, tool_name, self._job_name,
            )
            if self.audit_logger:
                self.audit_logger.log_tool_call(tool_name, arguments, "gate_timeout")
            return False

        approved = bool(decision)
        event_label = "gate_approved" if approved else "gate_rejected"
        _log.info(
            "%s: action=%s tool=%s job=%s agent=%s",
            event_label, action_id, tool_name, self._job_name, self._agent_name,
        )
        if self.audit_logger:
            self.audit_logger.log_tool_call(tool_name, arguments, event_label)
        return approved

    def resolve(self, action_id: str, approved: bool) -> None:
        """Called by the channel bot handler when the user taps Approve or Reject."""
        with self._lock:
            if action_id in self._pending:
                self._decisions[action_id] = approved
                self._pending[action_id].set()

    # ------------------------------------------------------------------
    # Transport dispatch
    # ------------------------------------------------------------------

    def _send(self, action_id: str, tool_name: str, arguments: dict, source: str) -> bool:
        from alfard.interfaces.telegram_notifier import TelegramNotifier
        from alfard.interfaces.discord_notifier import DiscordNotifier
        from alfard.interfaces.slack_notifier import SlackNotifier

        if isinstance(self._notifier, TelegramNotifier):
            return self._send_telegram(action_id, tool_name, arguments, source)
        if isinstance(self._notifier, DiscordNotifier):
            return self._send_discord(action_id, tool_name, arguments, source)
        if isinstance(self._notifier, SlackNotifier):
            return self._send_slack(action_id, tool_name, arguments, source)
        _log.error(
            "gate_send_failure: unsupported notifier type %s",
            type(self._notifier).__name__,
        )
        return False

    def _send_telegram(
        self,
        action_id: str,
        tool_name: str,
        arguments: dict,
        source: str,
    ) -> bool:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        args_text = json.dumps(arguments, indent=2)
        text = (
            f"*Cron approval required*\n\n"
            f"*Job:* `{self._job_name}`\n"
            f"*Agent:* `{self._agent_name}`\n"
            f"*Tool:* `{tool_name}`\n"
            f"*Scheduled:* `{self._scheduled_time}`\n"
            f"*Source:* `{source}`\n\n"
            f"*Arguments:*\n```\n{args_text}\n```\n\n"
            f"⏱ Timeout in {_TIMEOUT // 60} minutes"
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve", callback_data=f"cron_gate:{action_id}:approve"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"cron_gate:{action_id}:reject"),
        ]])
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._notifier._bot.send_message(
                    chat_id=self._notifier._chat_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                ),
                self._notifier._loop,
            )
            future.result(timeout=10)
            return True
        except Exception as exc:
            _log.error("gate_send_failure telegram action=%s: %s", action_id, exc)
            return False

    def _send_discord(
        self,
        action_id: str,
        tool_name: str,
        arguments: dict,
        source: str,
    ) -> bool:
        args_text = json.dumps(arguments, indent=2)[:900]
        embed = discord.Embed(title="Cron approval required", color=0x5865F2)
        embed.add_field(name="Job",       value=f"`{self._job_name}`",       inline=True)
        embed.add_field(name="Agent",     value=f"`{self._agent_name}`",     inline=True)
        embed.add_field(name="Tool",      value=f"`{tool_name}`",            inline=True)
        embed.add_field(name="Scheduled", value=f"`{self._scheduled_time}`", inline=True)
        embed.add_field(name="Source",    value=f"`{source}`",               inline=True)
        embed.add_field(
            name="Arguments", value=f"```json\n{args_text}\n```", inline=False
        )
        embed.set_footer(text=f"⏱ Timeout in {_TIMEOUT // 60} minutes")

        view = _CronApprovalView(self, action_id, self._notifier.owner_id)
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._notifier._channel.send(embed=embed, view=view),
                self._notifier._loop,
            )
            msg = future.result(timeout=10)
            view._message = msg
            return True
        except Exception as exc:
            _log.error("gate_send_failure discord action=%s: %s", action_id, exc)
            return False

    def _send_slack(
        self,
        action_id: str,
        tool_name: str,
        arguments: dict,
        source: str,
    ) -> bool:
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
                    "text": (
                        f"*Cron approval required*\n\n"
                        f"*Job:* `{self._job_name}`  *Agent:* `{self._agent_name}`\n"
                        f"*Tool:* `{tool_name}`  *Scheduled:* `{self._scheduled_time}`\n"
                        f"*Source:* `{source}`"
                    ),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Arguments:*\n```{args_text}```",
                },
            },
            {
                "type": "actions",
                "block_id": f"cron_{action_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅  Approve"},
                        "style": "primary",
                        "value": "approved",
                        "action_id": f"cg_{action_id}_approve",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌  Reject"},
                        "style": "danger",
                        "value": "rejected",
                        "action_id": f"cg_{action_id}_reject",
                    },
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"⏱ Timeout in {_TIMEOUT // 60} minutes",
                    }
                ],
            },
        ]
        try:
            self._notifier.client.chat_postMessage(
                channel=self._notifier.channel,
                text=f"Cron approval required: {tool_name} ({job_name})",
                blocks=blocks,
            )
            return True
        except Exception as exc:
            _log.error("gate_send_failure slack action=%s: %s", action_id, exc)
            return False
