"""ChannelManager — registers and starts all channels simultaneously."""

import logging
import threading

from alfard.channels.base import BaseChannel

log = logging.getLogger("alfard.channels")


class ChannelManager:
    """Starts all registered channels; background channels run in daemon threads."""

    def __init__(self) -> None:
        self._channels: list[BaseChannel] = []
        self._audit = None

    def set_audit(self, audit) -> None:
        self._audit = audit

    def register(self, channel: BaseChannel) -> None:
        self._channels.append(channel)

    def names(self) -> list[str]:
        return [ch.get_name() for ch in self._channels]

    def start_all(self, main_channel: str = "terminal") -> None:
        """Start all channels.

        The main_channel runs in the calling thread (blocking).
        All others run in daemon threads — their crashes are caught and logged.
        """
        foreground = next(
            (ch for ch in self._channels if ch.get_name() == main_channel), None
        )
        background = [
            ch for ch in self._channels if ch.get_name() != main_channel
        ]

        for ch in background:
            t = threading.Thread(
                target=self._run_background,
                args=(ch,),
                name=f"alfard-channel-{ch.get_name()}",
                daemon=True,
            )
            t.start()

        if foreground:
            foreground.start()

    def _run_background(self, channel: BaseChannel) -> None:
        import traceback
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

    def stop_all(self) -> None:
        for ch in self._channels:
            try:
                ch.stop()
            except Exception:
                pass
