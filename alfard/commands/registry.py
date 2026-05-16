"""Command registry — registers and dispatches slash commands.
Works identically across CLI, Slack, and any other interface."""

from typing import Callable

_commands: dict[str, dict] = {}

def register(name: str, description: str, handler: Callable) -> None:
    """Register a slash command."""
    _commands[name.lstrip("/")] = {
        "name": name if name.startswith("/") else f"/{name}",
        "description": description,
        "handler": handler,
    }

def dispatch(command: str, context: dict) -> str | None:
    """
    Dispatch a slash command. Returns response string or None
    if command not found.

    context dict contains whatever the handler needs:
      agent_name, memory, loader, registry, llm, turn_count
    """
    key = command.lstrip("/").split()[0].lower()
    if key not in _commands:
        return None
    return _commands[key]["handler"](context)

def is_command(text: str) -> bool:
    """Return True if text starts with /"""
    return text.strip().startswith("/")

def list_commands() -> list[dict]:
    """Return all registered commands."""
    return sorted(_commands.values(), key=lambda c: c["name"])
