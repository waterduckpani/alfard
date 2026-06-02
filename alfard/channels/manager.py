"""ChannelManager — registers and starts all channels simultaneously."""

import datetime
import logging
import threading
import traceback
from typing import Callable

from alfard.channels.base import BaseChannel

log = logging.getLogger("alfard.channels")

_WATCHDOG_INTERVAL = 30  # seconds between liveness checks
_MAX_FAILURES = 3


class ChannelManager:
    """Starts all registered channels; background channels run in daemon threads."""

    def __init__(self) -> None:
        self._channels: list[BaseChannel] = []
        self._audit = None
        # Part A: registry of running threads and their restart callables
        self._channel_threads: dict[str, tuple[threading.Thread, Callable]] = {}
        self._channel_failures: dict[str, int] = {}
        self._notified_down: set[str] = set()
        self._shutdown = threading.Event()

    def set_audit(self, audit) -> None:
        self._audit = audit

    def register(self, channel: BaseChannel) -> None:
        self._channels.append(channel)

    def names(self) -> list[str]:
        return [ch.get_name() for ch in self._channels]

    def _start_channel_thread(self, ch: BaseChannel) -> threading.Thread:
        t = threading.Thread(
            target=self._run_background,
            args=(ch,),
            name=f"alfard-channel-{ch.get_name()}",
            daemon=True,
        )
        t.start()
        return t

    def start_all(self, main_channel: str = "terminal") -> None:
        """Start all channels.

        The main_channel runs in the calling thread (blocking).
        All others run in daemon threads — their crashes are caught, logged, and
        watched by the channel watchdog which restarts them on failure.
        """
        foreground = next(
            (ch for ch in self._channels if ch.get_name() == main_channel), None
        )
        background = [
            ch for ch in self._channels if ch.get_name() != main_channel
        ]

        for ch in background:
            t = self._start_channel_thread(ch)
            name = ch.get_name()
            self._channel_threads[name] = (t, lambda _ch=ch: self._start_channel_thread(_ch))
            self._channel_failures[name] = 0

        if background:
            threading.Thread(
                target=self._channel_watchdog,
                name="alfard-channel-watchdog",
                daemon=True,
            ).start()

        if foreground:
            foreground.start()

    # Part C: wrapper logs and re-raises so is_alive() goes False on crash
    def _run_background(self, channel: BaseChannel) -> None:
        try:
            channel.start()
        except Exception as exc:
            log.error("channel '%s' crashed: %s", channel.get_name(), exc, exc_info=True)
            print(
                f"\n[channel:{channel.get_name()}] crashed — {exc}\n"
                + traceback.format_exc(),
                flush=True,
            )
            if self._audit is not None:
                try:
                    self._audit._write({
                        "type": "channel_crash",
                        "channel": channel.get_name(),
                        "error": str(exc),
                    })
                except Exception:
                    pass
            raise

    # Part B: watchdog — polls every 30 s, never crashes the daemon
    def _channel_watchdog(self) -> None:
        while not self._shutdown.wait(_WATCHDOG_INTERVAL):
            try:
                self._check_channels()
            except Exception as exc:
                log.error("channel watchdog error: %s", exc, exc_info=True)

    def _check_channels(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        for name, (thread, start_fn) in list(self._channel_threads.items()):
            if thread.is_alive():
                # healthy — reset failure tracking
                self._channel_failures[name] = 0
                self._notified_down.discard(name)
                continue

            failures = self._channel_failures.get(name, 0) + 1
            self._channel_failures[name] = failures
            log.warning(
                "channel '%s' is not alive at %s — restart attempt %d",
                name, now, failures,
            )

            try:
                new_thread = start_fn()
                self._channel_threads[name] = (new_thread, start_fn)
            except Exception as exc:
                log.error(
                    "channel '%s' could not spawn restart thread: %s",
                    name, exc, exc_info=True,
                )

            if failures >= _MAX_FAILURES and name not in self._notified_down:
                self._notified_down.add(name)
                agent = self._resolve_agent_name()
                msg = (
                    f"⚠️ {name} channel is down and could not restart automatically. "
                    f"Run: alfard service restart {agent}"
                )
                self._send_to_alive_channel(name, msg)

        if self._channel_threads and not self._shutdown.is_set():
            if not any(t.is_alive() for t, _ in self._channel_threads.values()):
                log.error("all channels down — manual restart required")
                if self._audit is not None:
                    try:
                        self._audit._write({"type": "all_channels_down", "ts": now})
                    except Exception:
                        pass

    def _resolve_agent_name(self) -> str:
        for ch in self._channels:
            name = getattr(ch, "_agent_name", None)
            if name:
                return name
        return "?"

    def _send_to_alive_channel(self, failed_name: str, message: str) -> None:
        for name, (thread, _) in self._channel_threads.items():
            if name == failed_name or not thread.is_alive():
                continue
            ch = next((c for c in self._channels if c.get_name() == name), None)
            if ch is None:
                continue
            try:
                if ch.send_admin_message(message):
                    log.info("watchdog notification sent via '%s'", name)
                    return
            except Exception:
                pass
        log.warning(
            "watchdog: could not send notification for '%s' — no alive channel available",
            failed_name,
        )

    def stop_all(self) -> None:
        self._shutdown.set()
        for ch in self._channels:
            try:
                ch.stop()
            except Exception:
                pass
