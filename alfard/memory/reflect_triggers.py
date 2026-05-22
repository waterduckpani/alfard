"""Reflect triggers — message-count and inactivity-based reflect scheduling.

Two triggers, both per-agent, both in-memory only (not persisted to brain.db).
"""

import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alfard.llm.client import LLMClient
    from alfard.memory.manager import MemoryManager

_IDLE_MINUTES = 30
_IDLE_MIN_MSGS = 3
_WATCHER_INTERVAL_SECS = 60

_lock = threading.Lock()
_msg_counters: dict[str, int] = {}
_session_msg_counts: dict[str, int] = {}
_last_msg_times: dict[str, datetime] = {}
_idle_stop_events: dict[str, threading.Event] = {}


def on_user_message(
    agent_name: str,
    memory_manager: "MemoryManager",
    llm_client: "LLMClient",
    audit_log_path: Path,
    msg_interval: int,
) -> bool:
    """Increment the per-agent message counter; trigger reflect when threshold is reached.

    Returns True if reflect was triggered.
    """
    with _lock:
        _msg_counters[agent_name] = _msg_counters.get(agent_name, 0) + 1
        _session_msg_counts[agent_name] = _session_msg_counts.get(agent_name, 0) + 1
        _last_msg_times[agent_name] = datetime.utcnow()
        fire = _msg_counters[agent_name] >= msg_interval
        if fire:
            _msg_counters[agent_name] = 0
            _last_msg_times[agent_name] = datetime.utcnow()

    if fire:
        try:
            memory_manager.run_reflect(llm_client, audit_log_path, force=True)
        except Exception:
            pass
        return True
    return False


def start_idle_watcher(
    agent_name: str,
    memory_manager: "MemoryManager",
    llm_client: "LLMClient",
    audit_log_path: Path,
) -> None:
    """Start a background thread that fires reflect after IDLE_MINUTES of silence."""
    stop_event = threading.Event()

    with _lock:
        old = _idle_stop_events.get(agent_name)
        if old:
            old.set()
        _idle_stop_events[agent_name] = stop_event
        _last_msg_times[agent_name] = datetime.utcnow()
        _session_msg_counts[agent_name] = 0

    def _watch() -> None:
        idle_delta = timedelta(minutes=_IDLE_MINUTES)
        while not stop_event.wait(timeout=_WATCHER_INTERVAL_SECS):
            with _lock:
                last = _last_msg_times.get(agent_name)
                session_msgs = _session_msg_counts.get(agent_name, 0)

            if last is not None and session_msgs >= _IDLE_MIN_MSGS:
                if datetime.utcnow() - last >= idle_delta:
                    with _lock:
                        _msg_counters[agent_name] = 0
                        _last_msg_times[agent_name] = datetime.utcnow()
                    try:
                        memory_manager.run_reflect(llm_client, audit_log_path, force=True)
                    except Exception:
                        pass

    t = threading.Thread(
        target=_watch,
        daemon=True,
        name=f"reflect-idle-{agent_name}",
    )
    t.start()


def stop_idle_watcher(agent_name: str) -> None:
    """Signal the idle-watcher thread for this agent to exit."""
    with _lock:
        event = _idle_stop_events.pop(agent_name, None)
        _session_msg_counts.pop(agent_name, None)
    if event:
        event.set()
