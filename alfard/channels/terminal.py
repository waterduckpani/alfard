"""Terminal channel — full-screen chat TUI using prompt_toolkit Application."""

import asyncio
import re
import shutil
import sys
from collections import deque
from io import StringIO
from typing import Optional

import io
import os

import yaml
from prompt_toolkit import Application
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea
from rich.console import Console as RichConsole
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from alfard.channels.base import BaseChannel
from alfard.cli.theme import p
from alfard.cli.components import error_block
from alfard.gate.approval import QueueNotifier
from alfard.memory.notifications import drain as _drain_notifications
from alfard.memory import reflect_triggers
from alfard.memory.tools import _propose_memory
from alfard.paths import ALFARD_HOME

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"

_FAKE_NOTIFICATION_RE = re.compile(
    r"╭─\s*remembered.*?╰─[^\n]*\n?",
    re.DOTALL,
)

# Sentinel value placed in the input queue to signal a quit/interrupt.
_QUIT = "\x00quit"

_SLASH_COMMANDS = [
    ("/remember", "save a fact to memory"),
    ("/cancel",   "stop the current operation"),
    ("/reset",    "stop the current operation"),
    ("/que",      "queue a message for the next turn"),
    ("/guide",    "send guidance while the agent is running"),
    ("/help",     "list available commands"),
]


class _SlashCompleter(Completer):
    """Shows slash-command suggestions when input starts with '/'."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        # Only complete the first token (command name itself)
        if " " in text:
            return
        for cmd, meta in _SLASH_COMMANDS:
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=cmd,
                    display_meta=meta,
                )


def _strip_fake_notifications(text: str) -> str:
    return _FAKE_NOTIFICATION_RE.sub("", text).strip()


def _rich_to_ansi(renderable, width: Optional[int] = None) -> str:
    """Render a Rich renderable to an ANSI escape-code string."""
    if width is None:
        width = shutil.get_terminal_size((80, 24)).columns
    buf = StringIO()
    con = RichConsole(file=buf, highlight=False, force_terminal=True, width=width)
    con.print(renderable)
    return buf.getvalue()


def _read_msg_interval() -> int:
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        raw = cfg.get("memory", {}).get("reflect_message_interval", 20)
        return max(5, min(100, int(raw)))
    except Exception:
        return 20


class _ChatUI:
    """
    Full-screen prompt_toolkit Application that owns all visual state.

    Two regions:
      - transcript: scrollable ANSI feed, updated via append()
      - input bar: permanently pinned TextArea, Enter submits to input_queue
    """

    def __init__(self, agent_name: str, notifier: QueueNotifier) -> None:
        self._agent_name = agent_name
        self._notifier = notifier
        self._transcript: list[str] = []
        self.input_queue: asyncio.Queue = asyncio.Queue()
        self.running: bool = False   # True while the LLM is processing
        self._app: Optional[Application] = None

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build(self) -> Application:
        # --- Transcript ---
        def _get_transcript_text():
            return ANSI("".join(self._transcript))

        def _get_cursor_position() -> Point:
            # Returning the last line forces the Window to auto-scroll to bottom.
            lines = "".join(self._transcript).split("\n")
            return Point(x=0, y=max(0, len(lines) - 2))

        transcript_ctrl = FormattedTextControl(
            text=_get_transcript_text,
            focusable=False,
            show_cursor=False,
            get_cursor_position=_get_cursor_position,
        )
        transcript_win = Window(content=transcript_ctrl, wrap_lines=True)

        # --- Separator with live hint ---
        def _get_separator():
            w = shutil.get_terminal_size((80, 24)).columns
            if self._notifier.has_pending():
                hint = "  approve? y · yes   n · no  "
                hint_style = "class:approval"
            elif self.running:
                hint = "  esc · interrupt  "
                hint_style = "class:hint"
            else:
                hint = "  esc · quit  "
                hint_style = "class:hint"
            sep_len = max(2, w - len(hint) - 1)
            return [("class:separator", "─" * sep_len), (hint_style, hint)]

        separator_win = Window(
            content=FormattedTextControl(text=_get_separator, focusable=False),
            height=1,
        )

        # --- Input bar ---
        input_area = TextArea(
            height=1,
            prompt=[("class:arrow", "›  ")],
            multiline=False,
            wrap_lines=False,
            completer=_SlashCompleter(),
            complete_while_typing=True,
        )

        # --- Key bindings ---
        kb = KeyBindings()

        @kb.add("enter")
        def _on_enter(event):
            text = input_area.text
            input_area.text = ""
            self.input_queue.put_nowait(text)

        @kb.add("escape")
        @kb.add("c-c")
        def _on_exit(event):
            self.input_queue.put_nowait(_QUIT)

        # --- Assemble ---
        layout = Layout(
            HSplit([transcript_win, separator_win, input_area]),
            focused_element=input_area,
        )

        style = Style.from_dict({
            "separator": p.rule,
            "hint":      p.fg_faint,
            "approval":  f"bold {p.warn}",
            "arrow":     f"bold {p.fg_em}",
            # completion dropdown
            "completion-menu":                          f"bg:{p.rule} {p.fg}",
            "completion-menu.completion":               f"bg:{p.rule} {p.fg}",
            "completion-menu.completion.current":       f"bg:{p.fg_faint} {p.fg_em} bold",
            "completion-menu.meta.completion":          f"bg:{p.rule} {p.fg_faint}",
            "completion-menu.meta.completion.current":  f"bg:{p.fg_faint} {p.fg_dim}",
        })

        return Application(
            layout=layout,
            key_bindings=kb,
            style=style,
            full_screen=True,
            mouse_support=False,
        )

    # ------------------------------------------------------------------
    # Public interface used by the LLM loop
    # ------------------------------------------------------------------

    def append(self, text: str) -> None:
        """Append an ANSI string to the transcript and trigger a redraw."""
        self._transcript.append(text)
        if self._app is not None:
            self._app.invalidate()

    def set_running(self, value: bool) -> None:
        self.running = value
        if self._app is not None:
            self._app.invalidate()

    async def run_async(self) -> None:
        self._app = self._build()
        await self._app.run_async()

    def exit(self) -> None:
        if self._app is not None and self._app.is_running:
            self._app.exit()


class TerminalChannel(BaseChannel):
    """Interactive terminal chat loop for one agent."""

    def __init__(self, agent_name: str, orchestrator, audit, loader, registry) -> None:
        self._agent_name = agent_name
        self._orchestrator = orchestrator
        self._audit = audit
        self._loader = loader
        self._registry = registry

    def get_name(self) -> str:
        return "terminal"

    def stop(self) -> None:
        self._orchestrator.stop()

    def notify_memory_write(self, entry: dict, ui: Optional[_ChatUI] = None) -> None:
        mem_type = entry.get("type", "fact")
        content = entry.get("content", "")
        truncated = content[:80] + "…" if len(content) > 80 else content

        label = "⚠ mistake" if mem_type == "mistake" else mem_type
        border = p.warn if mem_type == "mistake" else p.fg_faint

        panel = Panel(
            Text(f'{label} · "{truncated}"', style="dim italic"),
            title="[dim]remembered[/dim]",
            title_align="left",
            border_style=border,
            expand=False,
            padding=(0, 1),
        )
        if ui is not None:
            ui.append(_rich_to_ansi(panel))
        else:
            from alfard.cli.theme import console
            console.print(panel)

    def start(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:  # noqa: C901
        agent = self._agent_name
        orchestrator = self._orchestrator
        audit = self._audit
        loader = self._loader
        loop = asyncio.get_running_loop()

        notifier = QueueNotifier()
        orchestrator._gate._notifier = notifier

        ui = _ChatUI(agent, notifier)

        def _render_approval_panel(tool_name: str, arguments: dict, source: str) -> None:
            """Called from the executor thread; renders the compact gate panel into the transcript."""
            import json as _json
            panel = Panel(
                f"[{p.fg_dim}]{tool_name}  ·  {source}[/]",
                title="approve?",
                title_align="left",
                border_style=p.fg_faint,
                expand=False,
                padding=(0, 1),
            )
            ui.append(_rich_to_ansi(panel))
            if arguments:
                args_panel = Panel(
                    f"[dim]{_json.dumps(arguments, indent=2)}[/dim]",
                    border_style="dim",
                    expand=False,
                    padding=(0, 1),
                )
                ui.append(_rich_to_ansi(args_panel))

        notifier.set_on_present(_render_approval_panel)

        # Silence MCP subprocess stderr (Node.js server noise) during the TUI session.
        # Errors still surface through the Python exception path and appear in the transcript.
        import alfard.integrations.mcp_client as _mcp_mod
        _orig_errlog = _mcp_mod._errlog
        _mcp_mod._errlog = open(os.devnull, "w")

        _turns = 0
        _outcome = "abandoned"
        _pending_queue: deque = deque()
        _msg_interval = _read_msg_interval()
        _user_msg_count = 0
        _first_message = True
        _current_task: Optional[asyncio.Task] = None

        reflect_triggers.start_idle_watcher(
            agent, loader.memory_manager, orchestrator._llm, audit.log_path,
        )

        ui.append(_rich_to_ansi(
            f"[{p.fg_faint}]type your message and press enter. "
            f"type exit or quit to stop.[/]\n"
        ))

        # ------------------------------------------------------------------
        # LLM processing loop (runs as an asyncio Task)
        # ------------------------------------------------------------------

        async def _run_llm(first_msg: str) -> None:
            nonlocal _turns, _user_msg_count
            current_msg: Optional[str] = first_msg
            try:
                while current_msg:
                    audit.log_user_correction(current_msg)
                    _propose_memory.set_user_message(current_msg)
                    _turn_notifications: list = []
                    try:
                        result = await loop.run_in_executor(
                            None, orchestrator.run, current_msg
                        )
                        _turn_notifications.extend(_drain_notifications())
                        response = _strip_fake_notifications(result or "")
                        _turns += 1
                        _user_msg_count += 1

                        ui.append(_rich_to_ansi(f"[{p.fg_em}]{agent}[/]"))
                        ui.append(_rich_to_ansi(Markdown(response)))
                        ui.append("\n")

                        for entry in _turn_notifications:
                            self.notify_memory_write(entry, ui)

                        triggered = reflect_triggers.on_user_message(
                            agent, loader.memory_manager,
                            orchestrator._llm, audit.log_path, _msg_interval,
                        )
                        if triggered:
                            ui.append(_rich_to_ansi(
                                f"[{p.fg_dim}]💡 reflect triggered — "
                                f"review with: alfard memory review[/]"
                            ))

                        if _user_msg_count >= 15:
                            _user_msg_count = 0
                            try:
                                orchestrator.checkpoint_session()
                                ui.append(_rich_to_ansi(f"[{p.fg_faint}]· memory updated[/]\n"))
                            except Exception:
                                pass

                    except Exception as exc:
                        _turn_notifications.extend(_drain_notifications())
                        ui.append(_rich_to_ansi(error_block(
                            agent=agent, state="failed",
                            headline=str(exc), explanation="",
                        )))

                    current_msg = _pending_queue.popleft() if _pending_queue else None
            finally:
                ui.set_running(False)

        # ------------------------------------------------------------------
        # Input dispatch loop (runs as an asyncio Task)
        # ------------------------------------------------------------------

        async def _input_loop() -> None:
            nonlocal _current_task, _outcome, _first_message

            while True:
                raw = await ui.input_queue.get()

                # Quit / interrupt signal
                if raw == _QUIT:
                    if _current_task and not _current_task.done():
                        orchestrator.stop()
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(_current_task), timeout=5.0
                            )
                        except Exception:
                            pass
                    _outcome = "completed"
                    ui.append(_rich_to_ansi(f"[{p.fg_dim}]goodbye.[/]\n"))
                    await asyncio.sleep(0.15)   # let goodbye render before exit
                    ui.exit()
                    return

                stripped = raw.strip()

                # Approval gate has highest priority
                if notifier.has_pending():
                    low = stripped.lower()
                    if low in ("y", "yes", "approve"):
                        notifier.post_response("y")
                        ui.append(_rich_to_ansi(f"[{p.ok}]· approved[/]\n\n"))
                    elif low in ("n", "no", "deny", "reject"):
                        notifier.post_response("n")
                        ui.append(_rich_to_ansi(f"[{p.warn}]· rejected[/]\n\n"))
                    else:
                        ui.append(_rich_to_ansi(
                            f"[{p.warn}]· type y to approve or n to deny[/]\n"
                        ))
                    continue

                cmd = stripped.lower()

                if cmd in ("exit", "quit", "q", "bye", "done"):
                    _outcome = "completed"
                    ui.append(_rich_to_ansi(f"[{p.fg_dim}]goodbye.[/]\n"))
                    await asyncio.sleep(0.15)
                    ui.exit()
                    return

                if not stripped:
                    continue

                if cmd.startswith("/remember "):
                    content = stripped[len("/remember "):].strip()
                    if content:
                        result = loader.memory_manager.write(
                            content, memory_type="fact", valence="neutral",
                            source="user_explicit", confidence=1.0,
                        )
                        ui.append(_rich_to_ansi(f"[{p.fg_dim}]{result}[/]\n"))
                        for entry in _drain_notifications():
                            self.notify_memory_write(entry, ui)
                    continue

                if cmd.startswith("/que "):
                    content = stripped[5:].strip()
                    if content:
                        _pending_queue.append(content)
                        ui.append(_rich_to_ansi(f"[{p.fg_faint}]· queued[/]\n"))
                    continue

                # Commands while LLM is running
                if ui.running:
                    if cmd in ("/new", "/reset", "/cancel"):
                        orchestrator.stop()
                        _pending_queue.clear()
                        ui.append(_rich_to_ansi(f"[{p.fg_faint}]· cancelled[/]\n"))
                        if _current_task and not _current_task.done():
                            try:
                                await asyncio.wait_for(
                                    asyncio.shield(_current_task), timeout=5.0
                                )
                            except (asyncio.TimeoutError, Exception):
                                ui.set_running(False)
                    elif cmd.startswith("/guide "):
                        content = stripped[7:].strip()
                        if content:
                            orchestrator.signal_guide(content)
                            ui.append(_rich_to_ansi(f"[{p.fg_faint}]· guidance sent[/]\n"))
                    else:
                        _pending_queue.append(stripped)
                        ui.append(_rich_to_ansi(f"[{p.fg_faint}]· queued[/]\n"))
                    continue

                # First message: build dynamic system prompt
                if _first_message:
                    system_prompt = loader.build_system_prompt(query=stripped)
                    orchestrator._memory._system_prompt = system_prompt
                    _first_message = False

                # Echo the user's message into the transcript
                ui.append(_rich_to_ansi(f"[bold {p.fg_em}]you[/]\n"))
                ui.append(stripped + "\n\n")

                ui.set_running(True)
                _current_task = asyncio.create_task(_run_llm(stripped))

        # ------------------------------------------------------------------
        # Run UI and input loop concurrently; clean up when either exits
        # ------------------------------------------------------------------

        app_task = asyncio.create_task(ui.run_async())
        inp_task = asyncio.create_task(_input_loop())

        try:
            done, pending = await asyncio.wait(
                {app_task, inp_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            _mcp_mod._errlog = _orig_errlog

            reflect_triggers.stop_idle_watcher(agent)

            exc_info = sys.exc_info()[1]
            if exc_info is not None and not isinstance(
                exc_info, (SystemExit, KeyboardInterrupt)
            ):
                _outcome = "failed"

            audit.log_session_end(
                outcome=_outcome,
                turns=_turns,
                tool_calls_total=audit._tool_calls_total,
                tool_calls_failed=audit._tool_calls_failed,
                corrections_detected=audit._corrections_detected,
            )
            audit.close()

            if _turns > 0:
                try:
                    messages = orchestrator._memory.get_messages()
                    turns = [
                        m for m in messages
                        if m["role"] in ("user", "assistant") and m.get("content")
                    ]
                    if len(turns) >= 2:
                        conv_text = "\n".join(
                            f"{m['role'].upper()}: {m['content'][:300]}"
                            for m in turns[-20:]
                        )
                        response = orchestrator._llm.complete([{
                            "role": "user",
                            "content": (
                                "Summarise this conversation in 2-3 sentences. "
                                "List 3-5 topic keywords. Be factual and concise.\n\n"
                                "Format:\nSummary: <text>\nTopics: <comma-separated keywords>\n\n"
                                + conv_text
                            ),
                        }])
                        raw_txt = response.get("content", "").strip()
                        summary = raw_txt
                        topics: list[str] = []
                        for line in raw_txt.splitlines():
                            if line.lower().startswith("summary:"):
                                summary = line[len("summary:"):].strip()
                            elif line.lower().startswith("topics:"):
                                topics = [
                                    t.strip()
                                    for t in line[len("topics:"):].split(",")
                                    if t.strip()
                                ]
                        if summary:
                            loader.memory_manager.save_session(
                                summary=summary, topics=topics,
                                turn_count=_turns, outcome=_outcome,
                            )
                            try:
                                new_proposals = loader.memory_manager.run_reflect(
                                    orchestrator._llm, audit.log_path
                                )
                                if new_proposals:
                                    from alfard.cli.theme import console
                                    console.print(
                                        f"[{p.fg_dim}]💡 {new_proposals} new memory proposals — "
                                        f"review with: alfard memory review[/]"
                                    )
                            except Exception:
                                pass
                except Exception as e:
                    from alfard.cli.theme import console
                    console.print(
                        f"[{p.fg_faint}]note: could not save session memory: {e}[/]"
                    )
