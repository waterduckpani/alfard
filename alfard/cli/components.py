"""alfard CLI components — Rich renderables built from the design spec."""

import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from alfard.cli.theme import p, c, console, capabilities

# ── Glyphs ────────────────────────────────────────────────────────────────────

GLYPHS = {
    "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
    "h": "─", "v": "│",
    "hh": "━", "hv": "┃",
    "filled": "●", "ring": "○", "half": "◐", "diamond": "◇",
    "check": "✓", "cross": "✗", "triangle": "▲",
    "right": "→", "indent": "↳",
    "branch": "├", "end": "└",
    "block": "█", "empty": "░",
}

ASCII_GLYPHS = {
    "tl": "+", "tr": "+", "bl": "+", "br": "+",
    "h": "-", "v": "|", "hh": "=", "hv": "|",
    "filled": "*", "ring": "o", "half": ".", "diamond": "o",
    "check": "v", "cross": "x", "triangle": "^",
    "right": "->", "indent": ">",
    "branch": "+", "end": "+",
    "block": "#", "empty": "-",
}

g = GLYPHS if capabilities.unicode else ASCII_GLYPHS

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
_RICH_MARKUP = re.compile(r"\[/?[^\]]*\]")


def _strip_markup(text: str) -> str:
    """Strip Rich markup tags and ANSI codes for width measurement."""
    return _ANSI_ESCAPE.sub("", _RICH_MARKUP.sub("", text))


def _visible_len(text: str) -> int:
    return len(_strip_markup(text))


# ── Wordmark ──────────────────────────────────────────────────────────────────

_BANNER_PATH = Path(__file__).parent.parent / "assets" / "banner.txt"


def wordmark() -> str:
    """Return the ALFARD wordmark as a multi-line Rich markup string, read from assets/banner.txt."""
    from rich.markup import escape
    art = _BANNER_PATH.read_text(encoding="utf-8")
    return "\n".join(f"[{p.fg_em}]{escape(line)}[/]" for line in art.splitlines())


def header_block(version: str = "") -> str:
    """Full startup header rendered as a plain string (not a Rich Panel)."""
    colored_wm = wordmark()

    parts = [colored_wm, ""]
    parts.append(f"[{p.fg_faint}]local AI agents, done right.[/]")
    if version:
        parts.append(f"[{p.fg_faint}]v{version}[/]")
    parts.append("")
    parts.append(f"[{p.rule}]{g['h'] * 44}[/]")
    return "\n".join(parts)


# ── Chip ──────────────────────────────────────────────────────────────────────

_CHIP_COLORS = {
    "ok": p.ok,
    "streaming": p.info,
    "running": p.info,
    "thinking": p.info,
    "needs approval": p.warn,
    "failed": p.err,
    "queued": p.fg_faint,
}


def chip(state: str, suffix: str = "") -> str:
    """Return a Rich markup chip string for the given state."""
    color = _CHIP_COLORS.get(state, p.fg_faint)
    label = state if not suffix else f"{state} · {suffix}"
    return f"[{color}]{label}[/]"


# ── Dot ───────────────────────────────────────────────────────────────────────

def dot(state: str) -> str:
    """Return a Rich markup dot indicator for the given state."""
    if state in ("ok", "streaming", "running"):
        return f"[{p.ok}]{g['filled']}[/]"
    elif state == "thinking":
        return f"[{p.info}]{g['half']}[/]"
    elif state == "needs approval":
        return f"[{p.warn}]{g['filled']}[/]"
    elif state == "failed":
        return f"[{p.err}]{g['filled']}[/]"
    else:  # queued
        return f"[{p.fg_faint}]{g['diamond']}[/]"


# ── Action Line ───────────────────────────────────────────────────────────────

def action_line(name: str, state: str, duration: str = "", width: int = 64) -> str:
    """Format a single action line with dot, name, chip and duration."""
    left = f"{dot(state)} {c('fg_em', name, bold=True)}"
    right = chip(state, duration)
    left_len = _visible_len(left)
    right_len = _visible_len(right)
    pad = max(1, width - left_len - right_len)
    return left + " " * pad + right


# ── Tool Card ─────────────────────────────────────────────────────────────────

def _is_path_or_url(value: str) -> bool:
    return value.startswith(("/", "~", "http://", "https://", "./", "../"))


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def tool_card(
    name: str,
    args: dict,
    state: str,
    duration: str = "",
    result: str = "",
    width: int = 66,
) -> str:
    """Render a rounded tool card box."""
    inner = width - 4

    title_text = f" tool · {name} "
    right_text = chip(state, duration)
    right_raw = _strip_markup(right_text)

    available = width - 2 - len(title_text) - len(right_raw) - 2
    fill = g["h"] * max(0, available)
    top = (
        f"[{p.rule}]{g['tl']}{g['h']}{title_text}{fill} [/]"
        f"{right_text}"
        f"[{p.rule}] {g['tr']}[/]"
    )

    rows = []
    for k, v in args.items():
        v_str = str(v)
        if _is_path_or_url(v_str):
            val_markup = f"[{p.cyan}]{v_str}[/]"
        elif _is_number(v_str):
            val_markup = f"[{p.magenta}]{v_str}[/]"
        else:
            val_markup = f"[{p.fg_em}]{v_str}[/]"
        col_width = 10
        key_padded = k.ljust(col_width)
        row_inner = f"  [{p.fg_faint}]{key_padded}[/] {val_markup}"
        row_raw_len = _visible_len(row_inner)
        pad = max(0, inner - row_raw_len)
        rows.append(
            f"[{p.rule}]{g['v']}[/]{row_inner}{' ' * pad}[{p.rule}]{g['v']}[/]"
        )

    bottom = f"[{p.rule}]{g['bl']}{g['h'] * (width - 2)}{g['br']}[/]"

    parts = [top] + rows + [bottom]
    if result:
        parts.append(f"  [{p.fg_faint}]{g['end']}[/] [{p.fg_dim}]{result}[/]")

    return "\n".join(parts)


# ── Banner ────────────────────────────────────────────────────────────────────

def banner(version: str, user: str = "", workspace: str = "") -> str:
    """Render the alfard startup banner (compact inline variant)."""
    triangle = f"[{p.fg_em}][bold]{g['triangle']}[/bold][/]"
    ver = f"[{p.fg_faint}]v{version}[/]"
    title = f"[{p.fg_em}][bold]alfard[/bold][/]"
    line1 = f"{triangle} {title}  · {ver}"

    lines = [line1, ""]

    if user:
        label = f"[{p.fg_dim}]{'signed in as':<14}[/]"
        val = f"[{p.fg_em}]{user}[/]"
        lines.append(f"{label} {val}")

    if workspace:
        label = f"[{p.fg_dim}]{'workspace':<14}[/]"
        val = f"[{p.fg_em}]{workspace}[/]"
        lines.append(f"{label} {val}")

    if user or workspace:
        lines.append("")

    help_text = (
        f"[{p.fg_faint}]type [/]"
        f"[{p.fg_em}]alfard help[/]"
        f"[{p.fg_faint}] to see what alfard can do.[/]"
    )
    lines.append(help_text)

    return "\n".join(lines)


# ── Plan ──────────────────────────────────────────────────────────────────────

def plan(steps: list[dict]) -> str:
    """Render a plan with done/current/pending steps."""
    lines = [f"[{p.fg_faint}]plan[/]"]
    for step in steps:
        text = step.get("text", "")
        state = step.get("state", "pending")
        if state == "done":
            icon = f"[{p.ok}]{g['check']}[/]"
            styled = f"[{p.fg_dim}]{text}[/]"
        elif state == "current":
            icon = f"[{p.info}]{g['half']}[/]"
            styled = f"[{p.fg_em}]{text}[/]"
        else:
            icon = f"[{p.fg_faint}]{g['ring']}[/]"
            styled = f"[{p.fg_dim}]{text}[/]"
        lines.append(f"  {icon}  {styled}")
    return "\n".join(lines)


# ── Table ─────────────────────────────────────────────────────────────────────

def alfard_table(
    columns: list[dict],
    rows: list[dict],
    width: int = 64,
) -> Table:
    """Build a styled Rich table matching the alfard design spec."""
    table = Table(
        show_header=True,
        show_edge=False,
        show_lines=False,
        header_style=f"{p.fg_faint}",
        box=None,
        padding=(0, 1),
    )

    for col in columns:
        align = col.get("align", "left")
        table.add_column(
            col["header"].upper(),
            justify=align,
            no_wrap=False,
        )

    for row in rows:
        cells = []
        for col in columns:
            val = str(row.get(col["key"], ""))
            cells.append(val)
        table.add_row(*cells)

    return table


# ── Error Block ───────────────────────────────────────────────────────────────

def error_block(
    agent: str,
    state: str,
    headline: str,
    explanation: str,
    trace: list[str] | None = None,
    next_actions: list[dict] | None = None,
    width: int = 64,
) -> str:
    """Render a heavy-rule error block."""
    trace = trace or []
    next_actions = next_actions or []

    color = p.warn if state == "needs approval" else p.err
    rule = f"[{color}]{g['hh'] * width}[/]"
    spine = f"[{color}]{g['hv']}[/]"

    lines = [
        rule,
        f"{spine} [{p.fg_em}]{agent}[/]  [{p.fg_faint}]·[/]  [{color}]{state}[/]",
        f"{spine}",
        f"{spine} [{p.fg_dim}]{headline}[/]",
    ]

    if explanation:
        lines.append(f"{spine}")
        lines.append(f"{spine} [{p.fg_dim}]{explanation}[/]")

    lines.append(rule)

    if trace:
        lines.append("")
        for t in trace:
            lines.append(f"  [{p.fg_faint}]{t}[/]")

    if next_actions:
        lines.append("")
        lines.append(f"  [{p.fg_dim}]what next[/]")
        for action in next_actions:
            cmd = action.get("cmd", "")
            desc = action.get("desc", "")
            lines.append(
                f"    [{p.fg_faint}]{g['indent']}[/] [{p.fg_em}]{cmd}[/]"
                f"{'   ' + desc if desc else ''}"
            )

    return "\n".join(lines)


# ── Approval Block ────────────────────────────────────────────────────────────

def approval_block(
    agent: str,
    reason: str,
    fields: dict,
    width: int = 64,
) -> str:
    """Render a heavy amber approval block."""
    color = p.warn
    rule = f"[{color}]{g['hh'] * width}[/]"
    spine = f"[{color}]{g['hv']}[/]"

    lines = [
        rule,
        f"{spine} [{p.fg_em}]{agent}[/]  [{p.fg_faint}]·[/]  [{color}]needs approval[/]",
        f"{spine}",
        f"{spine} [{p.fg_dim}]{reason}[/]",
        f"{spine}",
    ]

    for k, v in fields.items():
        key_markup = f"[{p.fg_faint}]{k:<12}[/]"
        val_markup = f"[{p.fg_em}]{v}[/]"
        lines.append(f"{spine}  {key_markup} {val_markup}")

    lines.append(rule)
    lines.append("")

    approve = f"[{p.ok}]approve[/]"
    deny = f"[{p.err}]deny[/]"
    edit_ = f"[{p.fg_em}]edit[/]"
    footer = (
        f"[{p.fg_dim}]type [/]{approve}[{p.fg_dim}] to send · type [/]"
        f"{deny}[{p.fg_dim}] to discard · type [/]"
        f"{edit_}[{p.fg_dim}] to revise.[/]"
    )
    lines.append(footer)

    return "\n".join(lines)


# ── Spinner ───────────────────────────────────────────────────────────────────

class _SpinnerHandle:
    def __init__(self, live: Live | None, text: str, color_val: str):
        self._live = live
        self._text = text
        self._color = color_val

    def update(self, text: str) -> None:
        self._text = text
        if self._live:
            self._live.update(
                Spinner("dots", text=f"[{self._color}]{text}[/]", speed=1.25)
            )

    def succeed(self, text: str) -> None:
        if self._live:
            self._live.stop()
        console.print(f"[{p.ok}]{g['filled']}[/] [{p.ok}]{text}[/]")

    def fail(self, text: str) -> None:
        if self._live:
            self._live.stop()
        console.print(f"[{p.err}]{g['filled']}[/] [{p.err}]{text}[/]")

    def warn(self, text: str) -> None:
        if self._live:
            self._live.stop()
        console.print(f"[{p.warn}]{g['filled']}[/] [{p.warn}]{text}[/]")


@contextmanager
def alfard_spinner(text: str, color: str = "info") -> Generator[_SpinnerHandle, None, None]:
    """Context manager that shows a braille spinner while work is in progress.

    color: "info" = thinking, "ok" = tool work, "warn" = waiting, "err" = failing.
    Non-TTY fallback: prints once, no animation.
    """
    color_val = getattr(p, color, p.info)
    if capabilities.spinners:
        spinner = Spinner("dots", text=f"[{color_val}]{text}[/]", speed=1.25)
        with Live(spinner, console=console, refresh_per_second=12) as live:
            handle = _SpinnerHandle(live, text, color_val)
            yield handle
    else:
        console.print(f"[{color_val}]{text}[/]")
        yield _SpinnerHandle(None, text, color_val)


# ── Interactive Prompts ───────────────────────────────────────────────────────

def _quest_style():
    """Build a questionary prompt style from the current palette."""
    import questionary
    return questionary.Style([
        ("qmark", f"fg:{p.info}"),
        ("question", f"fg:{p.fg_em} bold"),
        ("pointer", f"fg:{p.info}"),
        ("highlighted", f"fg:{p.fg_em}"),
        ("selected", f"fg:{p.ok}"),
        ("instruction", f"fg:{p.fg_faint}"),
        ("text", f"fg:{p.fg}"),
        ("disabled", f"fg:{p.fg_faint} italic"),
        ("answer", f"fg:{p.fg_em}"),
        ("checkbox-selected", f"fg:{p.ok}"),
        ("separator", f"fg:{p.rule}"),
    ])


def alfard_select(
    question: str,
    choices: list,
    default: str | None = None,
) -> str | None:
    """Single-choice selector. Accepts strings, questionary.Choice, or questionary.Separator.

    Returns selected string, or None if interrupted.
    """
    import questionary
    return questionary.select(
        question,
        choices=choices,
        default=default,
        qmark="›",
        style=_quest_style(),
    ).ask()


def alfard_multiselect(
    question: str,
    choices: list,
    default: list[str] | None = None,
) -> list[str]:
    """Multi-choice selector. Accepts strings or questionary.Choice objects.

    Returns list of selected values (empty list if none selected or interrupted).
    """
    import questionary
    processed = []
    for ch in choices:
        if isinstance(ch, questionary.Choice):
            processed.append(ch)
        else:
            checked = bool(default and ch in default)
            processed.append(questionary.Choice(ch, checked=checked))
    result = questionary.checkbox(
        question,
        choices=processed,
        qmark="›",
        instruction="  space · a for all · enter to confirm",
        style=_quest_style(),
    ).ask()
    return result or []


def alfard_confirm(question: str, default: bool = True) -> bool:
    """Yes/no confirmation. Returns False if interrupted."""
    import questionary
    result = questionary.confirm(
        question,
        default=default,
        qmark="›",
        style=_quest_style(),
    ).ask()
    return bool(result)


def alfard_input(
    question: str,
    hint: str = "",
    password: bool = False,
    default: str = "",
    validate=None,
) -> str:
    """Text input prompt. Prints hint above the prompt if provided.

    Returns entered text, or default if interrupted.
    """
    import questionary
    if hint:
        console.print(f"  [{p.fg_faint}]{hint}[/]")
    style = _quest_style()
    if password:
        result = questionary.password(
            question,
            qmark="›",
            style=style,
            validate=validate,
        ).ask()
    else:
        result = questionary.text(
            question,
            qmark="›",
            style=style,
            default=default,
            validate=validate,
        ).ask()
    return result if result is not None else default
