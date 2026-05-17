"""Slack bot interface — runs alfard agents via Slack DMs and
channel mentions using Socket Mode. Approval gate requests appear
as interactive Slack messages."""

import os
import threading
import shutil
from pathlib import Path
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from alfard.agents.loader import AgentLoader, list_agents
from alfard.llm.client import LLMClient
from alfard.tools.registry import ToolRegistry
from alfard.audit.logger import AuditLogger
from alfard.gate.approval import ApprovalGate
from alfard.sandbox.executor import SandboxExecutor
from alfard.integrations.credentials import CredentialsManager
from alfard.integrations.mcp_client import MCPClient
from alfard.orchestrator.orchestrator import Orchestrator
from alfard.interfaces.slack_notifier import SlackNotifier
from alfard.commands.handlers import register_all


def _build_orchestrator(agent_name: str,
                        web_client: WebClient,
                        channel: str) -> tuple:
    """
    Build a full orchestrator wired to a SlackNotifier approval gate.
    Returns (orchestrator, audit).
    """
    loader = AgentLoader(agent_name)
    system_prompt = loader.build_system_prompt()

    registry = ToolRegistry()
    audit = AuditLogger()

    # Build approval gate with Slack notifier
    notifier = SlackNotifier(web_client, channel)
    gate = ApprovalGate(audit_logger=audit, notifier=notifier)

    sandbox = SandboxExecutor()
    credentials = CredentialsManager()

    mcp = MCPClient(registry)
    mcp.connect_all()

    gws_creds = Path.home() / ".config" / "gws" / "credentials.enc"
    if shutil.which("gws") and gws_creds.exists():
        from alfard.integrations.gws_tools import register_gmail_tools
        register_gmail_tools(registry)
    from alfard.integrations.gws_tools import register_gdrive_tools
    if shutil.which("gws") and gws_creds.exists():
        register_gdrive_tools(registry)

    from alfard.mounts.manager import MountManager, MountError
    from alfard.mounts.tools import register_file_tools
    try:
        mount_manager = MountManager(loader.agent_dir)
        if mount_manager.has_mounts():
            register_file_tools(registry, mount_manager)
    except MountError:
        pass  # log but don't crash the bot

    orchestrator = Orchestrator(
        llm=LLMClient(),
        registry=registry,
        audit=audit,
        gate=gate,
        sandbox=sandbox,
        credentials=credentials,
        system_prompt=system_prompt,
    )
    orchestrator._loader = loader
    orchestrator._agent_name = agent_name
    orchestrator._memory_manager = loader.memory_manager
    register_all()

    return orchestrator, audit, notifier


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
        load_dotenv()

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

        # Bot's own user ID (to ignore self-messages)
        auth = self.web_client.auth_test()
        self.bot_user_id = auth["user_id"]

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
        return self._sessions[channel]

    def _handle_message(self, channel: str, text: str,
                        user: str) -> None:
        """Process a message in a thread so Slack doesn't time out."""
        orchestrator, audit, notifier = self._get_session(channel)
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
                response = f"Something went wrong: {e}"

            # Post response
            self.web_client.chat_postMessage(
                channel=channel,
                text=_to_slack_mrkdwn(response)
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

            for action in actions:
                action_id = action.get("action_id", "")
                value = action.get("value", "")

                # Find which session this belongs to
                if channel in self._sessions:
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

    def start(self) -> None:
        """Start the bot. Blocks until Ctrl+C."""
        self.socket_client.socket_mode_request_listeners.append(
            self._process_request
        )
        self.socket_client.connect()
        print("[slack] connected. Send a DM to @alfard to start.")
        print("[slack] press Ctrl+C to stop.")

        import time
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[slack] stopping...")
            self.socket_client.close()
