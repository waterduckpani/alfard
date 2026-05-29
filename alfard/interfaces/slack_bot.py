"""Slack bot interface — runs alfard agents via Slack DMs and
channel mentions using Socket Mode. Approval gate requests appear
as interactive Slack messages."""

import os
import time
import threading
from collections import deque
from alfard.memory.notifications import drain as _drain_notifications
from alfard.paths import load_env
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

SESSION_TIMEOUT_HOURS = 4


def _build_orchestrator(agent_name: str,
                        web_client: WebClient,
                        channel: str) -> tuple:
    """
    Build a full orchestrator wired to a SlackNotifier approval gate.
    Returns (orchestrator, audit, notifier).
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
    return orchestrator, audit, notifier


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

        print(f"[slack] alfard bot ready — agent: {agent_name}")
        print(f"[slack] bot user id: {self.bot_user_id}")

    def _get_session(self, channel: str):
        """Get or create an orchestrator session for a channel."""
        if channel not in self._sessions:
            self._sessions[channel] = _build_orchestrator(
                self.agent_name, self.web_client, channel
            )
            self._locks[channel] = threading.Lock()
            self._first_message[channel] = True
            self._session_last_active[channel] = time.time()
            self._message_counts[channel] = 0
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
                _, audit, _ = self._sessions.pop(ch)
                audit.close()
            except Exception:
                pass
            self._locks.pop(ch, None)
            self._first_message.pop(ch, None)
            self._session_last_active.pop(ch, None)
            self._message_counts.pop(ch, None)
            self._pending_queues.pop(ch, None)
            self._session_user.pop(ch, None)

    def _handle_message(self, channel: str, text: str,
                        user: str) -> None:
        """Process a message in a thread so Slack doesn't time out."""
        self._session_last_active[channel] = time.time()
        stripped = text.strip()

        # /guide — signal the running orchestrator without acquiring the lock
        if stripped.lower().startswith("/guide "):
            guidance = stripped[7:].strip()
            if guidance and channel in self._sessions:
                orchestrator, _, _ = self._sessions[channel]
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
        orchestrator, audit, notifier = self._get_session(channel)
        self._session_user[channel] = user
        lock = self._locks[channel]

        with lock:  # one message at a time per channel
            if self._first_message.get(channel):
                system_prompt = orchestrator._loader.build_system_prompt(query=text)
                orchestrator._memory._system_prompt = system_prompt
                self._first_message[channel] = False

            # Show typing indicator
            try:
                self.web_client.chat_postMessage(
                    channel=channel,
                    text="_thinking..._"
                )
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

        # Handle interactive button clicks (approval gate)
        elif req.type == "interactive":
            payload = req.payload
            actions = payload.get("actions", [])
            channel = payload.get("channel", {}).get("id")
            message_ts = payload.get("message", {}).get("ts")
            pressing_user = payload.get("user", {}).get("id", "")

            for action in actions:
                action_id = action.get("action_id", "")
                value = action.get("value", "")

                # Find which session this belongs to
                if channel in self._sessions:
                    # Only the user who triggered the session may resolve gate requests.
                    expected_user = self._session_user.get(channel, "")
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

                    _, _, notifier = self._sessions[channel]
                    # action_id format: {uuid}_approve or {uuid}_reject
                    if "_approve" in action_id:
                        gate_id = action_id.replace("_approve", "")
                        notifier.resolve(gate_id, approved=True)
                        # Update the message to show approved
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
                                orchestrator, _, _ = self._sessions[channel]
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
