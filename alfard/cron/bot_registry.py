"""Process-level registry of running bot instances.

Bots register themselves on startup so the cron scheduler can inject
tasks into a live session instead of spawning a one-shot orchestrator.
"""

from __future__ import annotations

_bots: dict[tuple[str, str], object] = {}


def register(agent_name: str, channel_name: str, bot: object) -> None:
    """Register a running bot under (agent_name, channel_name)."""
    _bots[(agent_name, channel_name)] = bot


def deregister(agent_name: str, channel_name: str) -> None:
    """Remove a bot from the registry when it shuts down."""
    _bots.pop((agent_name, channel_name), None)


def get_bot(agent_name: str, channel_name: str) -> object | None:
    """Return the bot for (agent_name, channel_name), or None."""
    return _bots.get((agent_name, channel_name))
