"""Thread-local buffer for pending memory-write notifications.

Memory writes push entries here; the active channel drains after the reply.
"""

import threading

_local = threading.local()

_NOTIFY_SOURCES = frozenset({"agent_inferred", "user_explicit"})


def push(entry: dict) -> None:
    """Buffer a memory-write entry for the current thread."""
    if not hasattr(_local, "pending"):
        _local.pending = []
    _local.pending.append(entry)


def drain() -> list[dict]:
    """Remove and return all buffered entries for the current thread."""
    buf = getattr(_local, "pending", None)
    if not buf:
        return []
    result = list(buf)
    buf.clear()
    return result


def should_notify(source: str) -> bool:
    return source in _NOTIFY_SOURCES
