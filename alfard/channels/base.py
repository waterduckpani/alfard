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
        """Emit a notification after a successful brain.db write.

        Called after the full agent reply has been sent so as not to interrupt
        streaming. entry keys: type, content, source, valence, status.
        """

    @abstractmethod
    def post_cron_output(
        self,
        agent_name: str,
        job_name: str,
        run_ts: str,
        task: str,
        output: str,
        status: str = "completed",
    ) -> str | None:
        """Post cron job output to this channel.

        Returns a message_id string that can be used to identify thread replies
        later, or None if posting failed. Channel implementations call
        run_registry.register_run() after a successful post.
        """

    @abstractmethod
    def get_cron_run_from_event(self, event: dict) -> dict | None:
        """Given an incoming message event from this channel, return the cron
        run record if this message is a reply to a known cron run output.

        Returns None if the event is not a cron reply. Uses
        run_registry.lookup_run() or lookup_run_by_thread().
        """

    def is_cron_reply(self, event: dict) -> bool:
        return self.get_cron_run_from_event(event) is not None
