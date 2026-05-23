"""Telegram bot interface — routes messages to per-user alfard agent sessions.
Each Telegram user ID gets isolated conversation history; brain.db and soul.md
are shared across all channels."""

import asyncio
import logging
import os
import threading
import time

import yaml
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from alfard.memory.notifications import drain as _drain_notifications
from alfard.memory import reflect_triggers
from alfard.paths import ALFARD_HOME, load_env

SESSION_TIMEOUT_HOURS = 4
_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"
_log = logging.getLogger("alfard.telegram")


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
    bot,
    chat_id: int,
    loop: asyncio.AbstractEventLoop,
) -> tuple:
    from alfard.orchestrator.builder import build_orchestrator
    from alfard.interfaces.telegram_notifier import TelegramNotifier

    notifier = TelegramNotifier(bot, chat_id, loop)
    orchestrator, audit, loader, registry = build_orchestrator(
        agent_name=agent_name,
        notifier=notifier,
        connect_mcp=True,
        gate_enabled=True,
    )
    return orchestrator, audit, notifier, loader, registry


def _format_memory_notification(entry: dict) -> str:
    mem_type = entry.get("type", "fact")
    content = entry.get("content", "")
    truncated = content[:80] + "…" if len(content) > 80 else content
    label = "⚠ mistake" if mem_type == "mistake" else mem_type
    return f'_{label} · "{truncated}"_'


class AlfardTelegramBot:
    """Telegram bot that routes messages to per-user alfard agent sessions."""

    def __init__(self, agent_name: str) -> None:
        load_env()
        self.agent_name = agent_name
        self._token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not self._token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN not set. Run alfard channel connect telegram."
            )

        raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
        if raw:
            self._allowed: set[int] | None = {
                int(u) for u in raw.split(",") if u.strip().lstrip("-").isdigit()
            }
        else:
            self._allowed = None

        # user_id → (orchestrator, audit, notifier, loader, registry)
        self._sessions: dict[int, tuple] = {}
        self._locks: dict[int, threading.Lock] = {}
        self._first_message: dict[int, bool] = {}
        self._session_last_active: dict[int, float] = {}
        self._message_counts: dict[int, int] = {}
        self._msg_interval = _read_msg_interval()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_flag: asyncio.Event | None = None
        self._app: Application | None = None

        print(f"[telegram] alfard bot initialised — agent: {agent_name}")

    # ── access control ──────────────────────────────────────────────────────

    def _is_allowed(self, user_id: int) -> bool:
        return self._allowed is None or user_id in self._allowed

    # ── session management ───────────────────────────────────────────────────

    def _get_session(self, user_id: int, bot, loop: asyncio.AbstractEventLoop) -> tuple:
        if user_id not in self._sessions:
            session = _build_session(self.agent_name, bot, user_id, loop)
            self._sessions[user_id] = session
            self._locks[user_id] = threading.Lock()
            self._first_message[user_id] = True
            self._session_last_active[user_id] = time.time()
            self._message_counts[user_id] = 0
            _, audit, _, loader, _ = session
            reflect_triggers.start_idle_watcher(
                self.agent_name,
                loader.memory_manager,
                session[0]._llm,
                audit.log_path,
            )
        return self._sessions[user_id]

    def _evict_stale_sessions(self) -> None:
        cutoff = time.time() - (SESSION_TIMEOUT_HOURS * 3600)
        stale = [uid for uid, ts in self._session_last_active.items() if ts < cutoff]
        for uid in stale:
            try:
                _, audit, _, loader, _ = self._sessions.pop(uid)
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
                d.pop(uid, None)

    # ── message processing (sync, runs in thread) ────────────────────────────

    def _process_message(
        self,
        user_id: int,
        text: str,
        bot,
        loop: asyncio.AbstractEventLoop,
        reply_fn,
    ) -> None:
        self._session_last_active[user_id] = time.time()
        self._evict_stale_sessions()

        orchestrator, audit, notifier, loader, registry = self._get_session(
            user_id, bot, loop
        )
        lock = self._locks[user_id]

        with lock:
            if self._first_message.get(user_id):
                system_prompt = loader.build_system_prompt(query=text)
                orchestrator._memory._system_prompt = system_prompt
                self._first_message[user_id] = False

            try:
                response = orchestrator.run(text)
            except Exception as exc:
                _log.error(
                    "Error processing message for user %s: %s",
                    user_id, exc, exc_info=True,
                )
                response = "Something went wrong. Please try again."

            self._message_counts[user_id] = self._message_counts.get(user_id, 0) + 1
            if self._message_counts[user_id] >= 15:
                self._message_counts[user_id] = 0
                try:
                    orchestrator.checkpoint_session()
                except Exception:
                    pass

            reply_fn(response)

            for entry in _drain_notifications():
                try:
                    reply_fn(_format_memory_notification(entry))
                except Exception:
                    pass

        reflect_triggers.on_user_message(
            self.agent_name,
            loader.memory_manager,
            orchestrator._llm,
            audit.log_path,
            self._msg_interval,
        )

    # ── async handlers ───────────────────────────────────────────────────────

    async def _handle_message(self, update: Update, context) -> None:
        user_id = update.effective_user.id
        if not self._is_allowed(user_id):
            return

        text = (update.message.text or "").strip()
        if not text:
            return

        loop = asyncio.get_running_loop()
        chat_id = update.effective_chat.id

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        def _reply(msg: str) -> None:
            asyncio.run_coroutine_threadsafe(
                context.bot.send_message(chat_id=chat_id, text=msg),
                loop,
            ).result(timeout=30)

        threading.Thread(
            target=self._process_message,
            args=(user_id, text, context.bot, loop, _reply),
            daemon=True,
        ).start()

    async def _handle_new(self, update: Update, context) -> None:
        user_id = update.effective_user.id
        if not self._is_allowed(user_id):
            return

        if user_id not in self._sessions:
            await update.message.reply_text("No active session — send a message first.")
            return

        orchestrator, _, _, loader, _ = self._sessions[user_id]

        def _do_new() -> str:
            orchestrator.checkpoint_session()
            new_prompt = loader.build_system_prompt()
            orchestrator._memory._system_prompt = new_prompt
            orchestrator._memory.reset()
            self._first_message[user_id] = True
            return "Session saved. Starting fresh with updated memory."

        msg = await asyncio.get_running_loop().run_in_executor(None, _do_new)
        await update.message.reply_text(msg)

    async def _handle_remember(self, update: Update, context) -> None:
        user_id = update.effective_user.id
        if not self._is_allowed(user_id):
            return

        content = " ".join(context.args) if context.args else ""
        if not content:
            await update.message.reply_text("Usage: /remember <text to save>")
            return

        if user_id not in self._sessions:
            await update.message.reply_text("No active session — send a message first.")
            return

        _, _, _, loader, _ = self._sessions[user_id]
        loop = asyncio.get_running_loop()
        chat_id = update.effective_chat.id

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
                    context.bot.send_message(
                        chat_id=chat_id,
                        text=_format_memory_notification(entry),
                    ),
                    loop,
                )
            return result

        result = await loop.run_in_executor(None, _do_remember)
        await update.message.reply_text(result)

    async def _handle_callback(self, update: Update, context) -> None:
        query = update.callback_query
        await query.answer()

        data = query.data or ""
        if not data.startswith("gate:"):
            return

        parts = data.split(":")
        if len(parts) != 3:
            return

        _, action_id, decision = parts
        approved = decision == "approve"

        user_id = update.effective_user.id
        if user_id in self._sessions:
            _, _, notifier, _, _ = self._sessions[user_id]
            notifier.resolve(action_id, approved)

        label = "✅ Approved" if approved else "❌ Rejected"
        try:
            await query.edit_message_text(label)
        except Exception:
            pass

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def _async_run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_flag = asyncio.Event()

        app = ApplicationBuilder().token(self._token).build()
        self._app = app

        app.add_handler(CommandHandler("new", self._handle_new))
        app.add_handler(CommandHandler("remember", self._handle_remember))
        app.add_handler(CallbackQueryHandler(self._handle_callback))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        async with app:
            await app.updater.start_polling()
            await app.start()
            print("[telegram] connected. Send a message to start.")
            await self._stop_flag.wait()
            await app.updater.stop()
            await app.stop()

    def start(self) -> None:
        """Start the bot. Blocks until stop() is called."""
        asyncio.run(self._async_run())

    def stop(self) -> None:
        """Signal the bot to stop cleanly."""
        if self._loop and self._stop_flag:
            self._loop.call_soon_threadsafe(self._stop_flag.set)
        for uid in list(self._sessions):
            try:
                reflect_triggers.stop_idle_watcher(self.agent_name)
                _, audit, _, _, _ = self._sessions[uid]
                audit.close()
            except Exception:
                pass
