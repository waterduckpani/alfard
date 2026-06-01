"""Discord bot interface — routes messages to per-guild-channel alfard agent sessions.
Each guild+channel combination gets isolated conversation history; brain.db and
soul.md are shared across all channels."""

import asyncio
import logging
import os
import threading
import time
from typing import Optional

import discord
import yaml

from alfard.memory.notifications import drain as _drain_notifications
from alfard.memory import reflect_triggers
from alfard.memory.tools import _propose_memory
from alfard.paths import ALFARD_HOME, load_env

SESSION_TIMEOUT_HOURS = 4
_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"
_log = logging.getLogger("alfard.discord")

# (guild_id, channel_id) — guild_id is 0 for DMs
SessionKey = tuple[int, int]


def _read_msg_interval() -> int:
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        raw = cfg.get("memory", {}).get("reflect_message_interval", 20)
        return max(5, min(100, int(raw)))
    except Exception:
        return 20


def _build_session(
    agent_name: str,
    channel: discord.abc.Messageable,
    loop: asyncio.AbstractEventLoop,
) -> tuple:
    from alfard.orchestrator.builder import build_orchestrator
    from alfard.interfaces.discord_notifier import DiscordNotifier

    notifier = DiscordNotifier(channel, loop)
    orchestrator, audit, loader, registry = build_orchestrator(
        agent_name=agent_name,
        notifier=notifier,
        connect_mcp=True,
        gate_enabled=True,
    )
    return orchestrator, audit, notifier, loader, registry


def _memory_embed(entry: dict) -> discord.Embed:
    mem_type = entry.get("type", "fact")
    content = entry.get("content", "")
    truncated = content[:80] + "…" if len(content) > 80 else content
    label = "⚠ mistake" if mem_type == "mistake" else mem_type
    return discord.Embed(title=label, description=f'"{truncated}"', color=0x2ECC71)


class AlfardDiscordBot(discord.Client):
    """Discord bot that routes messages to per-guild-channel alfard agent sessions."""

    def __init__(self, agent_name: str) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        load_env()
        self.agent_name = agent_name
        self._token = os.environ.get("DISCORD_BOT_TOKEN")
        if not self._token:
            raise RuntimeError(
                "DISCORD_BOT_TOKEN not set. Run alfard channel connect discord."
            )

        raw = os.environ.get("DISCORD_ALLOWED_GUILDS", "").strip()
        if raw:
            self._allowed_guilds: set[int] | None = {
                int(g) for g in raw.split(",") if g.strip().isdigit()
            }
        else:
            self._allowed_guilds = None

        raw_dm = os.environ.get("DISCORD_ALLOWED_USERS", "").strip()
        if raw_dm:
            self._allowed_dm_users: set[int] | None = {
                int(u) for u in raw_dm.split(",") if u.strip().isdigit()
            }
        else:
            self._allowed_dm_users = None

        self._sessions: dict[SessionKey, tuple] = {}
        self._locks: dict[SessionKey, threading.Lock] = {}
        self._first_message: dict[SessionKey, bool] = {}
        self._session_last_active: dict[SessionKey, float] = {}
        self._message_counts: dict[SessionKey, int] = {}
        self._msg_interval = _read_msg_interval()
        self._loop: asyncio.AbstractEventLoop | None = None

        from alfard.cron import bot_registry
        bot_registry.register(agent_name, "discord", self)
        print(f"[discord] alfard bot initialised — agent: {agent_name}")

    # ── access control ───────────────────────────────────────────────────────

    def _is_guild_allowed(self, guild_id: Optional[int], author_id: int) -> bool:
        if self._allowed_guilds is None:
            return True
        if guild_id is not None:
            return guild_id in self._allowed_guilds
        if self._allowed_dm_users is None:
            return False
        return author_id in self._allowed_dm_users

    # ── session management ───────────────────────────────────────────────────

    def _get_session(
        self,
        key: SessionKey,
        channel: discord.abc.Messageable,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple:
        if key not in self._sessions:
            session = _build_session(self.agent_name, channel, loop)
            self._sessions[key] = session
            self._locks[key] = threading.Lock()
            self._first_message[key] = True
            self._session_last_active[key] = time.time()
            self._message_counts[key] = 0
            _, audit, _, loader, _ = session
            reflect_triggers.start_idle_watcher(
                self.agent_name,
                loader.memory_manager,
                session[0]._llm,
                audit.log_path,
            )
        return self._sessions[key]

    def _evict_stale_sessions(self) -> None:
        cutoff = time.time() - (SESSION_TIMEOUT_HOURS * 3600)
        stale = [k for k, ts in self._session_last_active.items() if ts < cutoff]
        for k in stale:
            try:
                _, audit, _, loader, _ = self._sessions.pop(k)
                reflect_triggers.stop_idle_watcher(self.agent_name)
                audit.close()
            except Exception:
                pass
            for d in (
                self._locks,
                self._first_message,
                self._session_last_active,
                self._message_counts,
            ):
                d.pop(k, None)

    # ── cron injection ───────────────────────────────────────────────────────

    def inject_cron_message(self, job_cfg: dict, job_name: str, task: str) -> None:
        """Inject a scheduled cron task into the live session for the cron channel.

        Resolves the target channel from DISCORD_CRON_CHANNEL_ID, looks up the
        channel object (to determine guild and get a Messageable), then runs the
        task through the normal session path in a background thread.
        """
        if self._loop is None:
            _log.error(
                "inject_cron_message: bot not ready yet (loop not set) "
                "job=%s agent=%s", job_name, self.agent_name,
            )
            return

        channel_id_str = os.environ.get("DISCORD_CRON_CHANNEL_ID")
        if not channel_id_str:
            _log.error(
                "inject_cron_message: DISCORD_CRON_CHANNEL_ID not set "
                "job=%s agent=%s", job_name, self.agent_name,
            )
            return

        try:
            channel_id = int(channel_id_str)
        except ValueError:
            _log.error(
                "inject_cron_message: invalid DISCORD_CRON_CHANNEL_ID %r job=%s",
                channel_id_str, job_name,
            )
            return

        # Resolve the channel object in the event loop, then spawn the injection thread.
        async def _resolve_and_inject() -> None:
            try:
                ch = self.get_channel(channel_id)
                if ch is None:
                    ch = await self.fetch_channel(channel_id)
            except Exception as exc:
                _log.error(
                    "inject_cron_message: could not resolve channel %s job=%s: %s",
                    channel_id, job_name, exc,
                )
                return
            threading.Thread(
                target=self._run_cron_injection,
                args=(ch, job_name, task),
                daemon=True,
            ).start()

        asyncio.run_coroutine_threadsafe(_resolve_and_inject(), self._loop)

    def _run_cron_injection(
        self,
        channel: discord.abc.Messageable,
        job_name: str,
        task: str,
    ) -> None:
        """Execute the cron task in the live session, then post output to the channel."""
        from alfard.cron.context import build_cron_context
        from alfard.cron.runner import _save_log
        from alfard.gate.cron_gate import CRON_ALWAYS_GATE
        from alfard.gate.approval import ToolDeniedError
        from alfard.agents.loader import AGENTS_DIR

        loop = self._loop
        if loop is None:
            return

        guild_id = channel.guild.id if hasattr(channel, "guild") and channel.guild else 0
        channel_id = channel.id
        key: SessionKey = (guild_id, channel_id)

        self._session_last_active[key] = time.time()
        self._evict_stale_sessions()
        orchestrator, audit, notifier, loader, registry = self._get_session(
            key, channel, loop
        )
        lock = self._locks[key]

        def _reply(msg: str) -> None:
            asyncio.run_coroutine_threadsafe(
                channel.send(msg), loop
            ).result(timeout=30)

        def _reply_embed(embed: discord.Embed) -> None:
            asyncio.run_coroutine_threadsafe(
                channel.send(embed=embed), loop
            ).result(timeout=30)

        with lock:
            if self._first_message.get(key):
                system_prompt = loader.build_system_prompt(query=task)
                orchestrator._memory._system_prompt = system_prompt
                self._first_message[key] = False

            cron_text = build_cron_context(job_name, task) + "\n\n" + task

            def _cron_hook(tool_name: str, arguments: dict) -> None:
                if tool_name in CRON_ALWAYS_GATE:
                    raise ToolDeniedError(
                        f"{tool_name} blocked by CRON_ALWAYS_GATE"
                    )

            orchestrator.pre_tool_hook = _cron_hook

            try:
                _reply(f"🤖 {job_name} running...")
            except Exception:
                pass

            try:
                response = orchestrator.run(cron_text)
            except Exception as exc:
                _log.error(
                    "cron injection error job=%s agent=%s: %s",
                    job_name, self.agent_name, exc, exc_info=True,
                )
                response = f"Cron job '{job_name}' encountered an error: {exc}"
            finally:
                orchestrator.pre_tool_hook = None

            self._message_counts[key] = self._message_counts.get(key, 0) + 1
            if self._message_counts[key] >= 15:
                self._message_counts[key] = 0
                try:
                    orchestrator.checkpoint_session()
                except Exception:
                    pass

            agent_name = getattr(orchestrator, "_agent_name", self.agent_name)
            embed = discord.Embed(
                title=f"🤖 {agent_name} · {job_name}",
                description=(response[:3900] + "…") if len(response) > 3900 else response,
                color=0x5865F2,
            )
            try:
                _reply_embed(embed)
            except Exception as exc:
                _log.error(
                    "failed to post cron output job=%s: %s", job_name, exc
                )

            for entry in _drain_notifications():
                try:
                    _reply_embed(_memory_embed(entry))
                except Exception:
                    pass

        try:
            _save_log(AGENTS_DIR / agent_name, job_name, task, response, error=False)
        except Exception:
            pass

        reflect_triggers.on_user_message(
            self.agent_name,
            loader.memory_manager,
            orchestrator._llm,
            audit.log_path,
            self._msg_interval,
        )

    # ── message processing (sync, runs in thread pool) ───────────────────────

    def _process_message(
        self,
        key: SessionKey,
        text: str,
        channel: discord.abc.Messageable,
        loop: asyncio.AbstractEventLoop,
        reply_fn,
        reply_embed_fn,
        author_id: int = 0,
    ) -> None:
        self._session_last_active[key] = time.time()
        self._evict_stale_sessions()

        orchestrator, audit, notifier, loader, registry = self._get_session(
            key, channel, loop
        )
        notifier.owner_id = author_id
        lock = self._locks[key]

        with lock:
            if self._first_message.get(key):
                system_prompt = loader.build_system_prompt(query=text)
                orchestrator._memory._system_prompt = system_prompt
                self._first_message[key] = False

            _propose_memory.set_user_message(text)

            try:
                response = orchestrator.run(text)
            except Exception as exc:
                _log.error(
                    "Error processing message for %s: %s", key, exc, exc_info=True
                )
                response = "Something went wrong. Please try again."

            self._message_counts[key] = self._message_counts.get(key, 0) + 1
            if self._message_counts[key] >= 15:
                self._message_counts[key] = 0
                try:
                    orchestrator.checkpoint_session()
                except Exception:
                    pass

            reply_fn(response)

            for entry in _drain_notifications():
                try:
                    reply_embed_fn(_memory_embed(entry))
                except Exception:
                    pass

        reflect_triggers.on_user_message(
            self.agent_name,
            loader.memory_manager,
            orchestrator._llm,
            audit.log_path,
            self._msg_interval,
        )

    # ── async event handlers ─────────────────────────────────────────────────

    async def on_ready(self) -> None:
        self._loop = asyncio.get_running_loop()
        print(f"[discord] connected as {self.user}. Send a message to start.")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        guild_id = message.guild.id if message.guild else None
        if not self._is_guild_allowed(guild_id, message.author.id):
            return

        text = message.content.strip()
        if not text:
            return

        if text.startswith("/"):
            await self._handle_command(message, guild_id)
            return

        loop = asyncio.get_running_loop()

        def _reply(msg: str) -> None:
            asyncio.run_coroutine_threadsafe(
                message.channel.send(msg),
                loop,
            ).result(timeout=30)

        def _reply_embed(embed: discord.Embed) -> None:
            asyncio.run_coroutine_threadsafe(
                message.channel.send(embed=embed),
                loop,
            ).result(timeout=30)

        key: SessionKey = (guild_id or 0, message.channel.id)

        async with message.channel.typing():
            await loop.run_in_executor(
                None,
                self._process_message,
                key,
                text,
                message.channel,
                loop,
                _reply,
                _reply_embed,
                message.author.id,
            )

    async def _handle_command(
        self, message: discord.Message, guild_id: Optional[int]
    ) -> None:
        text = message.content.strip()
        key: SessionKey = (guild_id or 0, message.channel.id)
        loop = asyncio.get_running_loop()

        if text == "/new":
            if key not in self._sessions:
                await message.channel.send(
                    "No active session — send a message first."
                )
                return

            orchestrator, _, _, loader, _ = self._sessions[key]

            def _do_new() -> str:
                orchestrator.checkpoint_session()
                new_prompt = loader.build_system_prompt()
                orchestrator._memory._system_prompt = new_prompt
                orchestrator._memory.reset()
                self._first_message[key] = True
                return "Session saved. Starting fresh with updated memory."

            msg = await loop.run_in_executor(None, _do_new)
            await message.channel.send(msg)

        elif text == "/remember" or text.startswith("/remember "):
            content = text[len("/remember"):].strip()
            if not content:
                await message.channel.send("Usage: /remember <text to save>")
                return

            if key not in self._sessions:
                await message.channel.send(
                    "No active session — send a message first."
                )
                return

            _, _, _, loader, _ = self._sessions[key]

            def _do_remember() -> str:
                result = loader.memory_manager.write(
                    content,
                    memory_type="fact",
                    valence="neutral",
                    source="user_explicit",
                    confidence=1.0,
                )
                for entry in _drain_notifications():
                    asyncio.run_coroutine_threadsafe(
                        message.channel.send(embed=_memory_embed(entry)),
                        loop,
                    ).result(timeout=30)
                return result

            result = await loop.run_in_executor(None, _do_remember)
            await message.channel.send(result)

    # ── lifecycle ────────────────────────────────────────────────────────────

    def run_bot(self) -> None:
        """Start the bot. Blocks until stop() is called."""
        self.run(self._token, log_handler=None)

    def stop(self) -> None:
        """Signal the bot to stop cleanly."""
        from alfard.cron import bot_registry
        bot_registry.deregister(self.agent_name, "discord")
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.close(), self._loop)
        for k in list(self._sessions):
            try:
                reflect_triggers.stop_idle_watcher(self.agent_name)
                _, audit, _, _, _ = self._sessions[k]
                audit.close()
            except Exception:
                pass
