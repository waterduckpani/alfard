"""Slack channel — wraps AlfardSlackBot as a BaseChannel."""

import os

import yaml

from alfard.channels.base import BaseChannel
from alfard.paths import load_env, ALFARD_HOME


class SlackChannel(BaseChannel):
    """Connects the agent to Slack via Socket Mode."""

    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name
        self._bot = None

    def get_name(self) -> str:
        return "slack"

    def start(self) -> None:
        from alfard.interfaces.slack_bot import AlfardSlackBot
        self._bot = AlfardSlackBot(agent_name=self._agent_name)
        self._bot.start()

    def stop(self) -> None:
        if self._bot is None:
            return
        self._bot._stop_event.set()
        try:
            self._bot.socket_client.close()
        except Exception:
            pass

    def notify_memory_write(self, entry: dict) -> None:
        # Slack notifications are posted by AlfardSlackBot._handle_message()
        # after the response is sent, where the Slack channel ID is available.
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
        from alfard.cron import run_registry
        from alfard.interfaces.slack_bot import get_running_bot

        load_env()

        bot = get_running_bot()
        if bot is not None:
            wc = bot.web_client
        else:
            from slack_sdk import WebClient
            token = os.environ.get("SLACK_BOT_TOKEN")
            if not token:
                return None
            wc = WebClient(token=token)

        try:
            with open(ALFARD_HOME / "config" / "alfard.yaml") as f:
                cfg = yaml.safe_load(f) or {}
            channel = (
                cfg.get("cron", {}).get("slack_channel_id")
                or cfg.get("slack", {}).get("channel")
                or os.environ.get("SLACK_APPROVAL_CHANNEL")
            )
        except Exception:
            channel = os.environ.get("SLACK_APPROVAL_CHANNEL")

        if not channel:
            return None

        body = (output[:2900] + "…") if len(output) > 2900 else output
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🤖 {job_name}"},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Agent: {agent_name} · {run_ts}"}
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body or "_no output_"},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "Reply in this thread to continue"}
                ],
            },
        ]

        try:
            resp = wc.chat_postMessage(
                channel=channel,
                text=f"🤖 {job_name} · {agent_name}",
                blocks=blocks,
            )
            ts = resp.get("ts")
            if not ts:
                return None
            run_registry.register_run(
                job_name=job_name,
                agent_name=agent_name,
                run_ts=run_ts,
                channel="slack",
                message_id=ts,
                task=task,
                thread_id=ts,
                status=status,
            )
            return ts
        except Exception:
            return None

    def get_cron_run_from_event(self, event: dict) -> dict | None:
        from alfard.cron import run_registry

        thread_ts = event.get("thread_ts")
        if not thread_ts:
            return None
        return run_registry.lookup_run_by_thread("slack", thread_ts)
