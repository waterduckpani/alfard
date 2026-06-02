"""Abstract base class for all alfard channels."""

from abc import ABC, abstractmethod


class BaseChannel(ABC):
    """A channel is one interface through which a user interacts with an agent."""

    @abstractmethod
    def start(self) -> None:
        """Start the channel and block until it stops."""

    @abstractmethod
    def stop(self) -> None:
        """Signal the channel to stop."""

    @abstractmethod
    def get_name(self) -> str:
        """Return a short lowercase name for this channel (e.g. 'terminal', 'slack')."""

    @abstractmethod
    def notify_memory_write(self, entry: dict) -> None:
        """Emit a notification after a successful brain.db write."""

    def send_admin_message(self, text: str) -> bool:
        """Send an operator alert to this channel. Returns True on success."""
        return False

    def post_cron_output(
        self,
        agent_name: str,
        job_name: str,
        run_ts: str,
        task: str,
        output: str,
        status: str = "completed",
    ) -> str | None:
        """Post cron job output to this channel. No-op by default.

        Cron output is now delivered through the channel's live session via
        inject_cron_message on the bot. This method is kept for backward
        compatibility with any code that still calls it.
        """
        return None

    def get_cron_run_from_event(self, event: dict) -> dict | None:
        """Return the cron run record for a reply event, or None.

        No longer used for routing — cron follow-ups go through the live
        session automatically.
        """
        return None

    def is_cron_reply(self, event: dict) -> bool:
        return self.get_cron_run_from_event(event) is not None
