"""alfard CLI theme — palette, detection, and Rich helpers."""

import os
import select
import sys
import time
from dataclasses import dataclass
from rich.console import Console


@dataclass
class Palette:
    fg: str
    fg_em: str
    fg_dim: str
    fg_faint: str
    rule: str
    ok: str
    warn: str
    err: str
    info: str
    magenta: str
    cyan: str


_LIGHT = Palette(
    fg="#232220",
    fg_em="#14130F",
    fg_dim="#6E6960",
    fg_faint="#908A7E",
    rule="#C2BDB1",
    ok="#6B8E5A",
    warn="#C89B4A",
    err="#B85C5C",
    info="#6F8AA8",
    magenta="#9F6F8A",
    cyan="#5E9E9B",
)

_DARK = Palette(
    fg="#E5E0D3",
    fg_em="#F4EFE2",
    fg_dim="#A6A198",
    fg_faint="#7F7B72",
    rule="#3B3833",
    ok="#8AA876",
    warn="#DDB46B",
    err="#CC7777",
    info="#8AA4BD",
    magenta="#B68DA3",
    cyan="#80B5B2",
)

PALETTES = {"light": _LIGHT, "dark": _DARK}

_NAMED_FALLBACK = {
    "ok": "green",
    "warn": "yellow",
    "err": "red",
    "info": "blue",
    "magenta": "magenta",
    "cyan": "cyan",
    "fg_em": "bold",
    "fg_dim": "dim",
    "fg_faint": "dim",
    "fg": "",
    "rule": "dim",
}


@dataclass
class Capabilities:
    truecolor: bool
    unicode: bool
    color: bool
    spinners: bool


def _detect_capabilities() -> Capabilities:
    colorterm = os.environ.get("COLORTERM", "").lower()
    truecolor = colorterm in ("truecolor", "24bit")

    unicode_ = (
        "--ascii" not in sys.argv
        and sys.platform in ("darwin", "linux")
    )

    no_color = (
        "NO_COLOR" in os.environ
        or "--no-color" in sys.argv
        or not sys.stdout.isatty()
    )
    color = not no_color

    spinners = sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"

    return Capabilities(
        truecolor=truecolor,
        unicode=unicode_,
        color=color,
        spinners=spinners,
    )


def _osc11_query(timeout: float = 0.05) -> tuple[int, int, int] | None:
    """Query the terminal background color via OSC 11 escape sequence.

    Sends ESC ] 11 ; ? BEL to /dev/tty and reads back
    ESC ] 11 ; rgb:RRRR/GGGG/BBBB BEL. Returns (r, g, b) or None on failure.
    Only runs on Unix TTY terminals with non-dumb TERM.
    """
    if not sys.stdout.isatty():
        return None
    if os.environ.get("TERM", "") == "dumb":
        return None
    if sys.platform not in ("darwin", "linux"):
        return None

    try:
        import re
        import termios
        import tty

        tty_fd = os.open("/dev/tty", os.O_RDWR)
        old = termios.tcgetattr(tty_fd)
        try:
            tty.setraw(tty_fd)
            os.write(tty_fd, b"\x1b]11;?\x07")

            buf = b""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                remaining = max(0.0, deadline - time.monotonic())
                readable, _, _ = select.select([tty_fd], [], [], remaining)
                if not readable:
                    break
                buf += os.read(tty_fd, 64)
                m = re.search(
                    rb"\x1b\]11;rgb:"
                    rb"([0-9a-fA-F]{2,4})/([0-9a-fA-F]{2,4})/([0-9a-fA-F]{2,4})",
                    buf,
                )
                if m:
                    return (
                        int(m.group(1)[:2], 16),
                        int(m.group(2)[:2], 16),
                        int(m.group(3)[:2], 16),
                    )
        finally:
            termios.tcsetattr(tty_fd, termios.TCSADRAIN, old)
            os.close(tty_fd)
    except Exception:
        pass

    return None


def detect_theme() -> str:
    # 0. Saved user preference in alfard.yaml (ui.theme: light|dark).
    #    Only honoured when explicitly set — "auto" falls through.
    try:
        import yaml
        from alfard.paths import ALFARD_HOME
        _cfg_path = ALFARD_HOME / "config" / "alfard.yaml"
        if _cfg_path.exists():
            with open(_cfg_path) as _f:
                _cfg = yaml.safe_load(_f) or {}
            _saved = str(_cfg.get("ui", {}).get("theme", "")).lower()
            if _saved in ("light", "dark"):
                return _saved
    except Exception:
        pass

    # 1. Explicit override always wins.
    env = os.environ.get("ALFARD_THEME", "").lower()
    if env in ("light", "dark"):
        return env
    if "--theme=light" in sys.argv:
        return "light"
    if "--theme=dark" in sys.argv:
        return "dark"

    # 2. COLORFGBG — set by rxvt, konsole, some xterm derivatives.
    #    Last segment is the bg ANSI index; 7 or 15 means light terminal.
    colorfgbg = os.environ.get("COLORFGBG", "")
    if colorfgbg:
        parts = colorfgbg.split(";")
        try:
            last = int(parts[-1])
            if last in (7, 15):
                return "light"
            return "dark"
        except (ValueError, IndexError):
            pass

    # 3. OSC 11 probe — ask the terminal its actual background color.
    rgb = _osc11_query()
    if rgb is not None:
        r, g, b = rgb
        lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        return "light" if lum > 0.5 else "dark"

    # 4. Fallback — most terminals are dark.
    return "dark"


capabilities = _detect_capabilities()
theme = detect_theme()
p = PALETTES[theme]

console = Console(highlight=False)


def c(role: str, text: str, bold: bool = False) -> str:
    """Return a Rich markup string for the given palette role."""
    if not capabilities.color:
        return f"[bold]{text}[/bold]" if bold else text

    if capabilities.truecolor:
        hex_val = getattr(p, role, "")
        if not hex_val:
            return f"[bold]{text}[/bold]" if bold else text
        bold_prefix = "bold " if bold else ""
        return f"[{bold_prefix}{hex_val}]{text}[/]"
    else:
        named = _NAMED_FALLBACK.get(role, "")
        if not named:
            return f"[bold]{text}[/bold]" if bold else text
        bold_prefix = "bold " if bold else ""
        return f"[{bold_prefix}{named}]{text}[/]"


# Legacy aliases for backward compatibility with existing cmd_* files
PRIMARY = p.info
SUCCESS = p.ok
WARNING = p.warn
ERROR = p.err
DIM = p.fg_dim
HEADING = p.fg_em
BORDER = p.rule
PANEL_DEFAULT = p.rule
PANEL_SUCCESS = p.ok
PANEL_WARNING = p.warn
PANEL_ERROR = p.err
PANEL_GATE = p.fg_faint

ICON_OK = "✓"
ICON_FAIL = "✗"
ICON_ARROW = "→"
ICON_DOT = "·"
ICON_LOCK = "⚿"
