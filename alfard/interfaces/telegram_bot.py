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
from alfard.utils.md_convert import to_telegram_html

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

        # session key is chat_id (== user_id for DMs, channel/group id for groups)
        self._sessions: dict[int, tuple] = {}
        self._locks: dict[int, threading.Lock] = {}
        self._first_message: dict[int, bool] = {}
        self._session_last_active: dict[int, float] = {}
        self._message_counts: dict[int, int] = {}
        self._msg_interval = _read_msg_interval()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_flag: asyncio.Event | None = None
        self._app: Application | None = None

        from alfard.cron import bot_registry
        bot_registry.register(agent_name, "telegram", self)
        print(f"[telegram] alfard bot initialised — agent: {agent_name}")

    # ── access control ──────────────────────────────────────────────────────

    def _is_allowed(self, user_id: int) -> bool:
        return self._allowed is None or user_id in self._allowed

    # ── session management ───────────────────────────────────────────────────

    def _get_session(self, chat_id: int) -> tuple:
        """Get or create a session keyed by chat_id."""
        if chat_id not in self._sessions:
            if self._app is None or self._loop is None:
                raise RuntimeError("Bot is not running — cannot create session")
            session = _build_session(self.agent_name, self._app.bot, chat_id, self._loop)
            self._sessions[chat_id] = session
            self._locks[chat_id] = threading.Lock()
            self._first_message[chat_id] = True
            self._session_last_active[chat_id] = time.time()
            self._message_counts[chat_id] = 0
            orchestrator, audit, _, loader, _ = session

            def _notify_reflect(n: int, _cid: int = chat_id) -> None:
                import asyncio
                loop = self._loop
                bot = self._app.bot if self._app else None
                if bot is None or loop is None:
                    return
                text = f"_💡 reflect triggered ({n} proposal{'s' if n != 1 else ''}) — review with:_ `alfard memory review`"
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(chat_id=_cid, text=text, parse_mode="Markdown"),
                    loop,
                )

            reflect_triggers.start_idle_watcher(
                self.agent_name,
                loader.memory_manager,
                orchestrator._llm,
                audit.log_path,
                notify_callback=_notify_reflect,
            )
            orchestrator._on_reflect = _notify_reflect
        return self._sessions[chat_id]

    def _evict_stale_sessions(self) -> None:
        cutoff = time.time() - (SESSION_TIMEOUT_HOURS * 3600)
        stale = [cid for cid, ts in self._session_last_active.items() if ts < cutoff]
        for cid in stale:
            try:
                _, audit, _, loader, _ = self._sessions.pop(cid)
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
                d.pop(cid, None)

    # ── cron injection ───────────────────────────────────────────────────────

    def inject_cron_message(self, job_cfg: dict, job_name: str, task: str) -> None:
        """Inject a scheduled cron task into the live session for the cron chat.

        Resolves the target chat_id from TELEGRAM_CRON_CHAT_ID or the first
        entry in TELEGRAM_ALLOWED_USERS, then runs the task through the normal
        session path in a background thread.
        """
        if self._loop is None or self._app is None:
            _log.error(
                "inject_cron_message: bot not running yet job=%s agent=%s",
                job_name, self.agent_name,
            )
            return

        chat_id_str = os.environ.get("TELEGRAM_CRON_CHAT_ID")
        if not chat_id_str:
            raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
            parts = [u for u in raw.split(",") if u.strip().lstrip("-").isdigit()]
            chat_id_str = parts[0].strip() if parts else None

        if not chat_id_str:
            _log.error(
                "inject_cron_message: no chat_id configured "
                "(set TELEGRAM_CRON_CHAT_ID) job=%s agent=%s",
                job_name, self.agent_name,
            )
            return

        try:
            chat_id = int(chat_id_str)
        except ValueError:
            _log.error(
                "inject_cron_message: invalid chat_id %r job=%s",
                chat_id_str, job_name,
            )
            return

        gate_disabled = job_cfg.get("approval_gate") == "disabled"
        threading.Thread(
            target=self._run_cron_injection,
            args=(chat_id, job_name, task, gate_disabled),
            daemon=True,
        ).start()

    def _run_cron_injection(self, chat_id: int, job_name: str, task: str, gate_disabled: bool = False) -> None:
        """Execute the cron task in the live session, then send output to the chat."""
        from alfard.cron.context import build_cron_context
        from alfard.cron.runner import _save_log
        from alfard.gate.cron_gate import CRON_ALWAYS_GATE
        from alfard.gate.approval import ToolDeniedError
        from alfard.agents.loader import AGENTS_DIR

        self._session_last_active[chat_id] = time.time()
        self._evict_stale_sessions()

        try:
            orchestrator, audit, notifier, loader, registry = self._get_session(chat_id)
        except Exception as exc:
            _log.error(
                "cron injection: failed to get session chat_id=%s job=%s: %s",
                chat_id, job_name, exc,
            )
            return

        if gate_disabled:
            orchestrator._gate.enabled = False
        lock = self._locks[chat_id]

        def _reply(msg: str, parse_mode: str | None = None) -> None:
            if self._loop is None or self._app is None:
                return
            asyncio.run_coroutine_threadsafe(
                self._app.bot.send_message(chat_id=chat_id, text=msg, parse_mode=parse_mode),
                self._loop,
            ).result(timeout=30)

        with lock:
            if self._first_message.get(chat_id):
                system_prompt = loader.build_system_prompt(query=task)
                orchestrator._memory._system_prompt = system_prompt
                self._first_message[chat_id] = False

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

            self._message_counts[chat_id] = self._message_counts.get(chat_id, 0) + 1
            if self._message_counts[chat_id] >= 15:
                self._message_counts[chat_id] = 0
                try:
                    orchestrator.checkpoint_session()
                except Exception:
                    pass

            agent_name = getattr(orchestrator, "_agent_name", self.agent_name)
            try:
                _reply(
                    f"🤖 {agent_name} · {job_name}\n\n{to_telegram_html(response)}",
                    parse_mode="HTML",
                )
            except Exception as exc:
                _log.error(
                    "failed to send cron output job=%s: %s", job_name, exc
                )

            for entry in _drain_notifications():
                try:
                    _reply(_format_memory_notification(entry))
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

    # ── message processing (sync, runs in thread) ────────────────────────────

    def _process_message(
        self,
        chat_id: int,
        text: str,
        reply_fn,
        reply_html_fn=None,
    ) -> None:
        self._session_last_active[chat_id] = time.time()
        self._evict_stale_sessions()

        orchestrator, audit, notifier, loader, registry = self._get_session(chat_id)
        lock = self._locks[chat_id]

        with lock:
            if self._first_message.get(chat_id):
                system_prompt = loader.build_system_prompt(query=text)
                orchestrator._memory._system_prompt = system_prompt
                self._first_message[chat_id] = False

            try:
                response = orchestrator.run(text)
            except Exception as exc:
                _log.error(
                    "Error processing message for chat %s: %s",
                    chat_id, exc, exc_info=True,
                )
                response = "Something went wrong. Please try again."

            self._message_counts[chat_id] = self._message_counts.get(chat_id, 0) + 1
            if self._message_counts[chat_id] >= 15:
                self._message_counts[chat_id] = 0
                try:
                    orchestrator.checkpoint_session()
                except Exception:
                    pass

            _send_html = reply_html_fn or reply_fn
            _send_html(to_telegram_html(response))

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

        def _reply_html(msg: str) -> None:
            asyncio.run_coroutine_threadsafe(
                context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML"),
                loop,
            ).result(timeout=30)

        threading.Thread(
            target=self._process_message,
            args=(chat_id, text, _reply),
            kwargs={"reply_html_fn": _reply_html},
            daemon=True,
        ).start()

    async def _handle_new(self, update: Update, context) -> None:
        user_id = update.effective_user.id
        if not self._is_allowed(user_id):
            return

        chat_id = update.effective_chat.id
        if chat_id not in self._sessions:
            await update.message.reply_text("No active session — send a message first.")
            return

        orchestrator, _, _, loader, _ = self._sessions[chat_id]

        def _do_new() -> str:
            orchestrator.checkpoint_session()
            new_prompt = loader.build_system_prompt()
            orchestrator._memory._system_prompt = new_prompt
            orchestrator._memory.reset()
            self._first_message[chat_id] = True
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

        chat_id = update.effective_chat.id
        if chat_id not in self._sessions:
            await update.message.reply_text("No active session — send a message first.")
            return

        _, _, _, loader, _ = self._sessions[chat_id]
        loop = asyncio.get_running_loop()

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
                ).result(timeout=30)
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

        chat_id = update.effective_chat.id
        if chat_id in self._sessions:
            _, _, notifier, _, _ = self._sessions[chat_id]
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
        from alfard.cron import bot_registry
        bot_registry.deregister(self.agent_name, "telegram")
        for cid in list(self._sessions):
            try:
                reflect_triggers.stop_idle_watcher(self.agent_name)
                _, audit, _, _, _ = self._sessions[cid]
                audit.close()
            except Exception:
                pass
