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
