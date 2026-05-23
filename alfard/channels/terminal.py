"""Terminal channel — interactive CLI loop for a single alfard agent session."""

import asyncio
import re
import shutil
import sys
from collections import deque

import yaml
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console as _RichConsole
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from alfard.channels.base import BaseChannel
from alfard.cli.theme import p, console
from alfard.cli.components import error_block
from alfard.gate.approval import QueueNotifier
from alfard.memory.notifications import drain as _drain_notifications
from alfard.memory import reflect_triggers
from alfard.memory.tools import _propose_memory
from alfard.paths import ALFARD_HOME

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"

_PT_STYLE = Style.from_dict({
    "separator": p.rule,
    "arrow":     f"bold {p.fg_em}",
    "hint":      p.fg_faint,
    "approval":  p.warn,
})


def _read_msg_interval() -> int:
    try:
        with open(_CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        raw = cfg.get("memory", {}).get("reflect_message_interval", 20)
        return max(5, min(100, int(raw)))
    except Exception:
        return 20


_FAKE_NOTIFICATION_RE = re.compile(
    r"╭─\s*remembered.*?╰─[^\n]*\n?",
    re.DOTALL,
)


def _strip_fake_notifications(text: str) -> str:
    """Remove any ╭─ remembered ─╮ blocks the agent emitted as raw text."""
    return _FAKE_NOTIFICATION_RE.sub("", text).strip()


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

    def notify_memory_write(self, entry: dict, _con=None) -> None:
        c = _con or console
        mem_type = entry.get("type", "fact")
        content = entry.get("content", "")
        truncated = content[:80] + "…" if len(content) > 80 else content

        if mem_type == "mistake":
            label = "⚠ mistake"
            border_style = p.warn
        else:
            label = mem_type
            border_style = p.fg_faint

        text = Text(f'{label} · "{truncated}"', style="dim italic")
        panel = Panel(
            text,
            title="[dim]remembered[/dim]",
            title_align="left",
            border_style=border_style,
            expand=False,
            padding=(0, 1),
        )
        c.print(panel)

    def start(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:  # noqa: C901
        agent = self._agent_name
        orchestrator = self._orchestrator
        audit = self._audit
        loader = self._loader

        # Inject queue-based notifier so the approval gate routes through our loop.
        notifier = QueueNotifier()
        orchestrator._gate._notifier = notifier

        _turns = 0
        _outcome = "abandoned"
        _running = False
        _loop = asyncio.get_running_loop()

        def _message() -> list:
            w = shutil.get_terminal_size((80, 24)).columns
            if notifier.has_pending():
                hint = "  approve? y · yes   n · no  "
                hint_style = "class:approval"
            elif _running:
                hint = "  esc to interrupt  "
                hint_style = "class:hint"
            else:
                hint = "  esc to quit  "
                hint_style = "class:hint"
            sep_len = max(2, w - len(hint))
            return [
                ("class:separator", "─" * sep_len),
                (hint_style, hint),
                ("", "\n"),
                ("class:arrow", "›  "),
            ]

        _session = PromptSession(
            message=_message,
            style=_PT_STYLE,
            refresh_interval=0.5,
        )

        try:
            console.print(
                f"[{p.fg_faint}]type your message and press enter. "
                f"type exit or quit to stop.[/]\n"
            )

            first_message = True
            _user_message_count = 0
            _pending_queue: deque = deque()
            _msg_interval = _read_msg_interval()
            _current_task: asyncio.Task | None = None

            reflect_triggers.start_idle_watcher(
                agent,
                loader.memory_manager,
                orchestrator._llm,
                audit.log_path,
            )

            # Create a Rich console that writes to sys.stdout *after* patch_stdout
            # has replaced it, so ANSI output is injected above the prompt correctly.
            with patch_stdout(raw=True):
                _con = _RichConsole(file=sys.stdout, highlight=False, force_terminal=True)

                async def _run_llm_loop(first_msg: str) -> None:
                    nonlocal _turns, _user_message_count, _running
                    current_msg: str | None = first_msg
                    try:
                        while current_msg:
                            audit.log_user_correction(current_msg)
                            _propose_memory.set_user_message(current_msg)
                            _turn_notifications: list = []
                            try:
                                result = await _loop.run_in_executor(
                                    None, orchestrator.run, current_msg
                                )
                                _turn_notifications.extend(_drain_notifications())
                                response = _strip_fake_notifications(result or "")
                                _turns += 1
                                _user_message_count += 1
                                _con.print(f"[{p.fg_em}]{agent}[/]")
                                _con.print(Markdown(response))
                                _con.print()
                                for _entry in _turn_notifications:
                                    self.notify_memory_write(_entry, _con)

                                triggered = reflect_triggers.on_user_message(
                                    agent,
                                    loader.memory_manager,
                                    orchestrator._llm,
                                    audit.log_path,
                                    _msg_interval,
                                )
                                if triggered:
                                    _con.print(
                                        f"[{p.fg_dim}]💡 reflect triggered — "
                                        f"review with: alfard memory review[/]"
                                    )

                                if _user_message_count >= 15:
                                    _user_message_count = 0
                                    try:
                                        orchestrator.checkpoint_session()
                                        _con.print(f"[{p.fg_faint}]· memory updated[/]")
                                    except Exception:
                                        pass

                            except Exception as exc:
                                _turn_notifications.extend(_drain_notifications())
                                _con.print(error_block(
                                    agent=agent,
                                    state="failed",
                                    headline=str(exc),
                                    explanation="",
                                ))

                            current_msg = _pending_queue.popleft() if _pending_queue else None
                    finally:
                        _running = False

                while True:
                    try:
                        user_input = await _session.prompt_async()
                    except (KeyboardInterrupt, EOFError):
                        if _current_task and not _current_task.done():
                            orchestrator.stop()
                            try:
                                await asyncio.wait_for(
                                    asyncio.shield(_current_task), timeout=5.0
                                )
                            except Exception:
                                pass
                        _outcome = "completed"
                        _con.print(f"\n[{p.fg_dim}]goodbye.[/]")
                        break

                    stripped = user_input.strip()

                    # Approval gate takes priority over everything else.
                    if notifier.has_pending():
                        low = stripped.lower()
                        if low in ("y", "yes", "approve"):
                            notifier.post_response("y")
                        elif low in ("n", "no", "deny", "reject"):
                            notifier.post_response("n")
                        else:
                            _con.print(
                                f"[{p.warn}]· type y to approve or n to deny[/]"
                            )
                        continue

                    cmd = stripped.lower()

                    if cmd in ("exit", "quit", "q", "bye", "done"):
                        _outcome = "completed"
                        _con.print(f"[{p.fg_dim}]goodbye.[/]")
                        break

                    if not stripped:
                        continue

                    if stripped.lower().startswith("/remember "):
                        content = stripped[len("/remember "):].strip()
                        if content:
                            result = loader.memory_manager.write(
                                content,
                                memory_type="fact",
                                valence="neutral",
                                source="user_explicit",
                                confidence=1.0,
                            )
                            _con.print(f"[{p.fg_dim}]{result}[/]\n")
                            for _entry in _drain_notifications():
                                self.notify_memory_write(_entry, _con)
                        continue

                    if stripped.lower().startswith("/que "):
                        content = stripped[5:].strip()
                        if content:
                            _pending_queue.append(content)
                            _con.print(f"[{p.fg_faint}]· queued[/]")
                        continue

                    # Handle input while the LLM is running.
                    if _running:
                        if cmd in ("/new", "/reset", "/cancel"):
                            orchestrator.stop()
                            _pending_queue.clear()
                            _con.print(f"[{p.fg_faint}]· cancelled[/]")
                            if _current_task and not _current_task.done():
                                try:
                                    await asyncio.wait_for(
                                        asyncio.shield(_current_task), timeout=5.0
                                    )
                                except (asyncio.TimeoutError, Exception):
                                    _running = False
                        elif cmd.startswith("/guide "):
                            content = stripped[7:].strip()
                            if content:
                                orchestrator.signal_guide(content)
                                _con.print(f"[{p.fg_faint}]· guidance sent[/]")
                        else:
                            _pending_queue.append(stripped)
                            _con.print(f"[{p.fg_faint}]· queued[/]")
                        continue

                    # First message: build the dynamic system prompt.
                    if first_message:
                        system_prompt = loader.build_system_prompt(query=stripped)
                        orchestrator._memory._system_prompt = system_prompt
                        first_message = False

                    _con.print()
                    _running = True
                    _current_task = asyncio.create_task(_run_llm_loop(stripped))

        finally:
            reflect_triggers.stop_idle_watcher(agent)
            exc = sys.exc_info()[1]
            if exc is not None and not isinstance(exc, (SystemExit, KeyboardInterrupt)):
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
                        raw = response.get("content", "").strip()
                        summary = raw
                        topics: list[str] = []
                        for line in raw.splitlines():
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
                                summary=summary,
                                topics=topics,
                                turn_count=_turns,
                                outcome=_outcome,
                            )
                            try:
                                new_proposals = loader.memory_manager.run_reflect(
                                    orchestrator._llm, audit.log_path
                                )
                                if new_proposals:
                                    console.print(
                                        f"[{p.fg_dim}]💡 {new_proposals} new memory proposals — "
                                        f"review with: alfard memory review[/]"
                                    )
                            except Exception:
                                pass
                except Exception as e:
                    console.print(
                        f"[{p.fg_faint}]note: could not save session memory: {e}[/]"
                    )
