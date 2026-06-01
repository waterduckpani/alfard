"""Slack bot interface — runs alfard agents via Slack DMs and
channel mentions using Socket Mode. Approval gate requests appear
as interactive Slack messages."""

# Required Slack OAuth scopes:
# channels:history  — read messages in public channels
# groups:history    — read messages in private channels
# im:history        — read DMs (already present)
# chat:write        — post messages (already present)
# The app must subscribe to the 'message.channels' and
# 'message.groups' event types in addition to app_mention.

import os
import time
import threading
from collections import deque

import yaml

from alfard.memory.notifications import drain as _drain_notifications
from alfard.memory import reflect_triggers
from alfard.paths import load_env, ALFARD_HOME
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"

_running_bot: "AlfardSlackBot | None" = None


def get_running_bot() -> "AlfardSlackBot | None":
    return _running_bot


def _read_msg_interval() -> int:
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        raw = cfg.get("memory", {}).get("reflect_message_interval", 20)
        return max(5, min(100, int(raw)))
    except Exception:
        return 20


SESSION_TIMEOUT_HOURS = 4


def _build_orchestrator(agent_name: str,
                        web_client: WebClient,
                        channel: str) -> tuple:
    """
    Build a full orchestrator wired to a SlackNotifier approval gate.
    Returns (orchestrator, audit, notifier, loader).
    """
    from alfard.orchestrator.builder import build_orchestrator
    from alfard.interfaces.slack_notifier import SlackNotifier

    notifier = SlackNotifier(web_client, channel)
    orchestrator, audit, loader, registry = build_orchestrator(
        agent_name=agent_name,
        notifier=notifier,
        connect_mcp=True,
        gate_enabled=True,
    )
    return orchestrator, audit, notifier, loader


def _format_memory_notification(entry: dict) -> str:
    """Format a memory-write entry as a muted Slack mrkdwn follow-up."""
    mem_type = entry.get("type", "fact")
    content = entry.get("content", "")
    truncated = content[:80] + "…" if len(content) > 80 else content
    if mem_type == "mistake":
        label = "⚠ mistake"
    else:
        label = mem_type
    return f'_{label} · "{truncated}"_'


def _to_slack_mrkdwn(text: str) -> str:
    """Convert Markdown to Slack mrkdwn format."""
    import re
    # **bold** → *bold*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    # __bold__ → *bold*
    text = re.sub(r'__(.+?)__', r'*\1*', text)
    # *italic* or _italic_ → _italic_
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'_\1_', text)
    # ### heading → *heading*
    text = re.sub(r'^#{1,3}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)
    # - bullet → • bullet
    text = re.sub(r'^- ', '• ', text, flags=re.MULTILINE)
    return text


class AlfardSlackBot:
    """
    Slack bot that routes DMs and @mentions to an alfard agent.
    Uses Socket Mode — no public URL needed.
    """

    def __init__(self, agent_name: str):
        global _running_bot
        load_env()

        self.agent_name = agent_name
        self.bot_token = os.environ.get("SLACK_BOT_TOKEN")
        self.app_token = os.environ.get("SLACK_APP_TOKEN")

        if not self.bot_token:
            raise RuntimeError(
                "SLACK_BOT_TOKEN not set. Run alfard connect slack."
            )
        if not self.app_token:
            raise RuntimeError(
                "SLACK_APP_TOKEN not set. "
                "Generate an app-level token at api.slack.com/apps"
            )

        self.web_client = WebClient(token=self.bot_token)
        self.socket_client = SocketModeClient(
            app_token=self.app_token,
            web_client=self.web_client,
        )

        # Per-channel orchestrators (one per conversation)
        self._sessions: dict[str, tuple] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._first_message: dict[str, bool] = {}
        self._session_last_active: dict[str, float] = {}
        self._message_counts: dict[str, int] = {}
        self._pending_queues: dict[str, deque] = {}
        self._session_user: dict[str, str] = {}  # channel → user_id who triggered the session
        self._stop_event = threading.Event()
        self._msg_interval = _read_msg_interval()

        # Bot's own user ID (to ignore self-messages)
        auth = self.web_client.auth_test()
        self.bot_user_id = auth["user_id"]

        raw_allowed = os.environ.get("SLACK_ALLOWED_USERS", "").strip()
        if raw_allowed:
            self._allowed_users: set[str] | None = {
                u.strip() for u in raw_allowed.split(",") if u.strip()
            }
        else:
            self._allowed_users = None

        _running_bot = self
        from alfard.cron import bot_registry
        bot_registry.register(agent_name, "slack", self)
        print(f"[slack] alfard bot ready — agent: {agent_name}")
        print(f"[slack] bot user id: {self.bot_user_id}")

    def _get_session(self, channel: str, notify_channel: str | None = None):
        """Get or create an orchestrator session for a channel."""
        if channel not in self._sessions:
            self._sessions[channel] = _build_orchestrator(
                self.agent_name, self.web_client, notify_channel or channel
            )
            self._locks[channel] = threading.Lock()
            self._first_message[channel] = True
            self._session_last_active[channel] = time.time()
            self._message_counts[channel] = 0
            orchestrator, audit, notifier, loader = self._sessions[channel]
            reflect_triggers.start_idle_watcher(
                self.agent_name,
                loader.memory_manager,
                orchestrator._llm,
                audit.log_path,
            )
        return self._sessions[channel]

    def _evict_stale_sessions(self) -> None:
        """Close and remove sessions that have been idle too long."""
        cutoff = time.time() - (SESSION_TIMEOUT_HOURS * 3600)
        stale = [
            ch for ch, ts in self._session_last_active.items()
            if ts < cutoff
        ]
        for ch in stale:
            try:
                _, audit, _, loader = self._sessions.pop(ch)
                reflect_triggers.stop_idle_watcher(self.agent_name)
                audit.close()
            except Exception:
                pass
            self._locks.pop(ch, None)
            self._first_message.pop(ch, None)
            self._session_last_active.pop(ch, None)
            self._message_counts.pop(ch, None)
            self._pending_queues.pop(ch, None)
            self._session_user.pop(ch, None)

    def inject_cron_message(self, job_cfg: dict, job_name: str, task: str) -> None:
        """Inject a scheduled cron task into the live session for the cron channel.

        Resolves the target Slack channel from job_cfg or global config, then
        runs the task through the normal session path in a background thread.
        """
        channel = job_cfg.get("slack_channel_id")
        if not channel:
            try:
                with open(_CONFIG_PATH) as f:
                    cfg = yaml.safe_load(f) or {}
                channel = (
                    cfg.get("cron", {}).get("slack_channel_id")
                    or cfg.get("slack", {}).get("channel")
                    or os.environ.get("SLACK_APPROVAL_CHANNEL")
                )
            except Exception:
                channel = os.environ.get("SLACK_APPROVAL_CHANNEL")

        if not channel:
            import logging
            logging.getLogger("alfard.slack").error(
                "inject_cron_message: no Slack channel configured for job=%s agent=%s",
                job_name, self.agent_name,
            )
            return

        threading.Thread(
            target=self._run_cron_injection,
            args=(channel, job_name, task),
            daemon=True,
        ).start()

    def _run_cron_injection(self, channel: str, job_name: str, task: str) -> None:
        """Execute the cron task in the live session, then post output to the channel."""
        import logging
        from alfard.cron.context import build_cron_context
        from alfard.cron.runner import _save_log
        from alfard.agents.loader import AGENTS_DIR

        _log = logging.getLogger("alfard.slack")

        cron_session_key = f"{channel}:cron:{job_name}"
        self._session_last_active[cron_session_key] = time.time()
        self._evict_stale_sessions()
        orchestrator, audit, notifier, loader = self._get_session(cron_session_key, notify_channel=channel)
        lock = self._locks[cron_session_key]

        with lock:
            if self._first_message.get(cron_session_key):
                system_prompt = loader.build_system_prompt(query=task)
                orchestrator._memory._system_prompt = system_prompt
                self._first_message[cron_session_key] = False

            cron_text = build_cron_context(job_name, task) + "\n\n" + task

            thinking_ts = None
            try:
                resp = self.web_client.chat_postMessage(
                    channel=channel,
                    text=f"_🤖 {job_name} running..._",
                )
                thinking_ts = resp.get("ts")
            except Exception:
                pass

            error_occurred = False
            try:
                response = orchestrator.run(cron_text)
            except Exception as exc:
                _log.error(
                    "cron injection error job=%s agent=%s: %s",
                    job_name, self.agent_name, exc, exc_info=True,
                )
                response = f"Cron job '{job_name}' encountered an error: {exc}"
                error_occurred = True

            self._message_counts[cron_session_key] = self._message_counts.get(cron_session_key, 0) + 1
            if self._message_counts[cron_session_key] >= 15:
                self._message_counts[cron_session_key] = 0
                try:
                    orchestrator.checkpoint_session()
                except Exception:
                    pass

            if thinking_ts:
                try:
                    self.web_client.chat_delete(channel=channel, ts=thinking_ts)
                except Exception:
                    pass

            status_icon = "❌" if error_occurred else "✅"
            summary = response[:500] + "…" if len(response) > 500 else response
            try:
                self.web_client.chat_postMessage(
                    channel=channel,
                    text=f"*{status_icon} {job_name}*\n{summary}",
                )
            except Exception as exc:
                _log.error(
                    "failed to post cron output job=%s: %s", job_name, exc
                )

            for entry in _drain_notifications():
                try:
                    self.web_client.chat_postMessage(
                        channel=channel,
                        text=_format_memory_notification(entry),
                    )
                except Exception:
                    pass

        try:
            _save_log(AGENTS_DIR / agent_name, job_name, task, response, error=False)
        except Exception:
            pass

    def _handle_message(self, channel: str, text: str,
                        user: str) -> None:
        """Process a message in a thread so Slack doesn't time out."""
        self._session_last_active[channel] = time.time()
        stripped = text.strip()

        # /guide — signal the running orchestrator without acquiring the lock
        if stripped.lower().startswith("/guide "):
            guidance = stripped[7:].strip()
            if guidance and channel in self._sessions:
                orchestrator, _, _, _ = self._sessions[channel]
                orchestrator.signal_guide(guidance)
                try:
                    self.web_client.chat_postMessage(
                        channel=channel,
                        text="⏸ Guidance received — agent will adjust at the next step."
                    )
                except Exception:
                    pass
            elif guidance:
                try:
                    self.web_client.chat_postMessage(
                        channel=channel, text="No active session to guide."
                    )
                except Exception:
                    pass
            else:
                try:
                    self.web_client.chat_postMessage(
                        channel=channel, text="Usage: /guide <your guidance>"
                    )
                except Exception:
                    pass
            return

        # /que — add to queue without acquiring the lock, acknowledge immediately
        if stripped.lower().startswith("/que "):
            queued = stripped[5:].strip()
            if queued:
                if channel not in self._pending_queues:
                    self._pending_queues[channel] = deque()
                self._pending_queues[channel].append(queued)
                try:
                    self.web_client.chat_postMessage(
                        channel=channel,
                        text=f"✓ Queued — will send after the current turn finishes."
                    )
                except Exception:
                    pass
            return

        self._evict_stale_sessions()
        orchestrator, audit, notifier, loader = self._get_session(channel)
        lock = self._locks[channel]

        with lock:  # one message at a time per channel
            self._session_user[channel] = user

            if self._first_message.get(channel):
                system_prompt = loader.build_system_prompt(query=text)
                orchestrator._memory._system_prompt = system_prompt
                self._first_message[channel] = False

            # Show typing indicator and capture its ts for later deletion
            thinking_ts = None
            try:
                thinking_resp = self.web_client.chat_postMessage(
                    channel=channel,
                    text="_thinking..._"
                )
                thinking_ts = thinking_resp.get("ts")
            except Exception:
                pass

            try:
                response = orchestrator.run(text)
            except Exception as e:
                import logging
                logging.getLogger("alfard.slack").error(
                    f"Error in _handle_message: {e}", exc_info=True
                )
                response = "Something went wrong. Please try again."

            self._message_counts[channel] = self._message_counts.get(channel, 0) + 1
            if self._message_counts[channel] >= 15:
                self._message_counts[channel] = 0
                try:
                    orchestrator.checkpoint_session()
                except Exception:
                    pass

            # Delete the thinking stub before posting the real response
            if thinking_ts:
                try:
                    self.web_client.chat_delete(channel=channel, ts=thinking_ts)
                except Exception:
                    pass

            # Post response
            self.web_client.chat_postMessage(
                channel=channel,
                text=_to_slack_mrkdwn(response)
            )

            # Emit memory-write notifications buffered during this turn
            for _entry in _drain_notifications():
                try:
                    self.web_client.chat_postMessage(
                        channel=channel,
                        text=_format_memory_notification(_entry),
                    )
                except Exception:
                    pass

            # Drain any messages queued with /que during this turn
            pending = self._pending_queues.get(channel)
            while pending:
                next_msg = pending.popleft()
                try:
                    queued_response = orchestrator.run(next_msg)
                    self._message_counts[channel] = self._message_counts.get(channel, 0) + 1
                    self.web_client.chat_postMessage(
                        channel=channel,
                        text=_to_slack_mrkdwn(queued_response)
                    )
                except Exception:
                    pass

        reflect_triggers.on_user_message(
            self.agent_name,
            loader.memory_manager,
            orchestrator._llm,
            audit.log_path,
            self._msg_interval,
        )

    def _process_request(self, client: SocketModeClient,
                         req: SocketModeRequest) -> None:
        """Handle incoming Socket Mode requests."""

        # Always acknowledge immediately
        client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )

        # Handle events
        if req.type == "events_api":
            event = req.payload.get("event", {})
            event_type = event.get("type")

            # Ignore bot's own messages
            if event.get("bot_id") or event.get("user") == self.bot_user_id:
                return

            # DM message
            if event_type == "message" and event.get("channel_type") == "im":
                channel = event["channel"]
                text = event.get("text", "").strip()
                user = event.get("user", "")
                if self._allowed_users is not None and user not in self._allowed_users:
                    try:
                        self.web_client.chat_postEphemeral(
                            channel=channel,
                            user=user,
                            text="You are not authorised to use this bot.",
                        )
                    except Exception:
                        pass
                    return
                if text:
                    threading.Thread(
                        target=self._handle_message,
                        args=(channel, text, user),
                        daemon=True,
                    ).start()

            # @mention in channel
            elif event_type == "app_mention":
                channel = event["channel"]
                text = event.get("text", "")
                user = event.get("user", "")
                if self._allowed_users is not None and user not in self._allowed_users:
                    try:
                        self.web_client.chat_postEphemeral(
                            channel=channel,
                            user=user,
                            text="You are not authorised to use this bot.",
                        )
                    except Exception:
                        pass
                    return
                # Strip the @mention from the text
                import re
                text = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()
                if text:
                    threading.Thread(
                        target=self._handle_message,
                        args=(channel, text, user),
                        daemon=True,
                    ).start()

            # Message in a channel where we have a live session (cron channel or
            # any channel the bot was explicitly added to via inject_cron_message).
            elif event_type == "message" and event.get("channel_type") in ("channel", "group"):
                if event.get("subtype") == "bot_message" or event.get("bot_id"):
                    return
                channel = event["channel"]
                # Only respond in channels where we already have a session.
                # Sessions are created by inject_cron_message, so this naturally
                # restricts responses to the configured cron channel.
                if channel not in self._sessions:
                    return
                text = event.get("text", "").strip()
                user = event.get("user", "")
                if not text:
                    return
                if self._allowed_users is not None and user not in self._allowed_users:
                    try:
                        self.web_client.chat_postEphemeral(
                            channel=channel,
                            user=user,
                            text="You are not authorised to use this bot.",
                        )
                    except Exception:
                        pass
                    return
                threading.Thread(
                    target=self._handle_message,
                    args=(channel, text, user),
                    daemon=True,
                ).start()

        # Handle interactive button clicks (approval gate)
        elif req.type == "interactive":
            payload = req.payload
            actions = payload.get("actions", [])
            channel = payload.get("channel", {}).get("id")
            message_ts = payload.get("message", {}).get("ts")
            pressing_user = payload.get("user", {}).get("id", "")

            for action in actions:
                action_id = action.get("action_id", "")

                # Find which session this belongs to — check direct key first,
                # then fall back to any cron session for the same channel.
                session_key = None
                if channel in self._sessions:
                    session_key = channel
                else:
                    prefix = f"{channel}:cron:"
                    for key in self._sessions:
                        if key.startswith(prefix):
                            session_key = key
                            break

                if session_key is not None:
                    # Only the user who triggered an interactive session may
                    # resolve gate requests.  Cron sessions have no session
                    # owner so any allowed user may approve.
                    expected_user = self._session_user.get(session_key, "")
                    if expected_user and pressing_user != expected_user:
                        try:
                            self.web_client.chat_postEphemeral(
                                channel=channel,
                                user=pressing_user,
                                text="You are not authorised to approve or reject this action.",
                            )
                        except Exception:
                            pass
                        continue

                    _, _, notifier, _ = self._sessions[session_key]
                    # action_id format: {uuid}_approve or {uuid}_reject
                    if "_approve" in action_id:
                        gate_id = action_id.replace("_approve", "")
                        notifier.resolve(gate_id, approved=True)
                        try:
                            self.web_client.chat_update(
                                channel=channel,
                                ts=message_ts,
                                text="✅ Approved",
                                blocks=[]
                            )
                        except Exception:
                            pass
                    elif "_reject" in action_id:
                        gate_id = action_id.replace("_reject", "")
                        notifier.resolve(gate_id, approved=False)
                        try:
                            self.web_client.chat_update(
                                channel=channel,
                                ts=message_ts,
                                text="❌ Rejected",
                                blocks=[]
                            )
                        except Exception:
                            pass

    def _check_inactivity(self) -> None:
        """Background thread: checkpoint conversations idle > 30 min with ≥ 3 messages."""
        while not self._stop_event.wait(600):  # check every 10 minutes
            cutoff = time.time() - 1800  # 30 minutes
            for channel, last_active in list(self._session_last_active.items()):
                if last_active < cutoff and self._message_counts.get(channel, 0) >= 3:
                    lock = self._locks.get(channel)
                    if lock is None:
                        continue
                    with lock:
                        if self._message_counts.get(channel, 0) >= 3:
                            self._message_counts[channel] = 0
                            try:
                                orchestrator, _, _, _ = self._sessions[channel]
                                orchestrator.checkpoint_session()
                            except Exception:
                                pass

    def start(self) -> None:
        """Start the bot. Blocks until Ctrl+C."""
        self.socket_client.socket_mode_request_listeners.append(
            self._process_request
        )
        self.socket_client.connect()
        print("[slack] connected. Send a DM to @alfard to start.")
        print("[slack] press Ctrl+C to stop.")

        threading.Thread(
            target=self._check_inactivity, daemon=True, name="alfard-inactivity"
        ).start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[slack] stopping...")
            self._stop_event.set()
            self.socket_client.close()
            from alfard.cron import bot_registry
            bot_registry.deregister(self.agent_name, "slack")
