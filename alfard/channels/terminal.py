"""Terminal channel — interactive CLI loop for a single alfard agent session."""

import re
import select
import sys
import threading
from collections import deque

import yaml
from prompt_toolkit import PromptSession
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text

from alfard.channels.base import BaseChannel
from alfard.cli.theme import p, console
from alfard.cli.components import error_block
from alfard.gate.approval import _STDIN_LOCK
from alfard.memory.notifications import drain as _drain_notifications
from alfard.memory import reflect_triggers
from alfard.memory.tools import _propose_memory
from alfard.paths import ALFARD_HOME

_CONFIG_PATH = ALFARD_HOME / "config" / "alfard.yaml"


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

    def notify_memory_write(self, entry: dict) -> None:
        mem_type = entry.get("type", "fact")
        content = entry.get("content", "")
        truncated = content[:80] + "…" if len(content) > 80 else content

        if mem_type == "mistake":
            label = "⚠ mistake"
            border_style = p.warn
        else:
            label = mem_type
            border_style = p.fg_faint

        text = Text(f'{label} · "{truncated}"', style=f"dim italic")
        panel = Panel(
            text,
            title="[dim]remembered[/dim]",
            title_align="left",
            border_style=border_style,
            expand=False,
            padding=(0, 1),
        )
        console.print(panel)

    def start(self) -> None:  # noqa: C901  (complexity lives here by necessity)
        agent = self._agent_name
        orchestrator = self._orchestrator
        audit = self._audit
        loader = self._loader
        registry = self._registry

        _turns = 0
        _outcome = "abandoned"
        _session = PromptSession()

        try:
            console.print(
                f"[{p.fg_faint}]type your message and press enter. "
                f"type exit or quit to stop.[/]\n"
            )

            first_message = True
            _user_message_count = 0
            _pending_queue: deque = deque()
            _msg_interval = _read_msg_interval()
            reflect_triggers.start_idle_watcher(
                agent,
                loader.memory_manager,
                orchestrator._llm,
                audit.log_path,
            )

            while True:
                if _pending_queue:
                    stripped = _pending_queue.popleft()
                    console.print(f"[{p.fg_faint}]· auto: {stripped}[/]")
                else:
                    try:
                        user_input = _session.prompt("you › ")
                    except (KeyboardInterrupt, EOFError):
                        console.print(f"\n[{p.fg_dim}]goodbye.[/]")
                        break

                    stripped = user_input.strip()
                    cmd = stripped.lower()

                    if cmd in ("exit", "quit", "q", "bye", "done"):
                        _outcome = "completed"
                        console.print(f"[{p.fg_dim}]goodbye.[/]")
                        break

                    if not stripped:
                        continue

                    if stripped.lower().startswith("/remember "):
                        content = stripped[len("/remember "):].strip()
                        if content:
                            result = loader.memory_manager.write(
                                content, memory_type="fact", valence="neutral",
                                source="user_explicit", confidence=1.0,
                            )
                            console.print(f"[{p.fg_dim}]{result}[/]\n")
                            for _entry in _drain_notifications():
                                self.notify_memory_write(_entry)
                        continue

                    if stripped.lower().startswith("/que "):
                        content = stripped[5:].strip()
                        if content:
                            _pending_queue.append(content)
                            console.print(f"[{p.fg_faint}]· queued for next turn[/]")
                        continue

                    if stripped.lower().startswith("/guide"):
                        console.print(
                            f"[{p.fg_faint}]· /guide works while the agent is running[/]"
                        )
                        continue

                audit.log_user_correction(stripped)
                _propose_memory.set_user_message(stripped)

                if first_message:
                    system_prompt = loader.build_system_prompt(query=stripped)
                    orchestrator._memory._system_prompt = system_prompt
                    first_message = False

                _result: list = [None, None]  # [response, exception]
                _turn_notifications: list = []
                _done = threading.Event()

                def _run_turn(msg: str = stripped) -> None:
                    try:
                        _result[0] = orchestrator.run(msg)
                    except Exception as exc:
                        _result[1] = exc
                    finally:
                        # Harvest notifications from this thread before signalling done.
                        _turn_notifications.extend(_drain_notifications())
                        _done.set()

                console.print()
                _thread = threading.Thread(target=_run_turn, daemon=True)
                _thread.start()

                try:
                    while not _done.wait(timeout=0.1):
                        if _STDIN_LOCK.acquire(blocking=False):
                            try:
                                ready, _, _ = select.select([sys.stdin], [], [], 0)
                                if ready:
                                    mid = sys.stdin.readline().rstrip("\n").strip()
                                    if mid.lower().startswith("/que "):
                                        content = mid[5:].strip()
                                        if content:
                                            _pending_queue.append(content)
                                            console.print(f"[{p.fg_faint}]· queued: '{content}'[/]")
                                    elif mid.lower().startswith("/guide "):
                                        content = mid[7:].strip()
                                        if content:
                                            orchestrator.signal_guide(content)
                                            console.print(
                                                f"[{p.fg_faint}]· guidance sent[/]"
                                            )
                                    elif mid:
                                        console.print(
                                            f"[{p.fg_faint}]· agent is running — use /que or /guide[/]"
                                        )
                            finally:
                                _STDIN_LOCK.release()
                except KeyboardInterrupt:
                    orchestrator.stop()
                    _done.wait()
                    _thread.join(timeout=5)
                    orchestrator.reset()
                    console.print(f"\n[{p.fg_dim}]interrupted.[/]\n")
                    continue

                _thread.join()

                if _result[1] is not None:
                    console.print(error_block(
                        agent=agent,
                        state="failed",
                        headline=str(_result[1]),
                        explanation="",
                    ))
                    continue

                response = _strip_fake_notifications(_result[0] or "")
                _turns += 1
                _user_message_count += 1
                console.print(f"[{p.fg_em}]{agent}[/]")
                console.print(Markdown(response))
                console.print()
                for _entry in _turn_notifications:
                    self.notify_memory_write(_entry)

                triggered = reflect_triggers.on_user_message(
                    agent,
                    loader.memory_manager,
                    orchestrator._llm,
                    audit.log_path,
                    _msg_interval,
                )
                if triggered:
                    console.print(
                        f"[{p.fg_dim}]💡 reflect triggered — review with: alfard memory review[/]"
                    )

                if _user_message_count >= 15:
                    _user_message_count = 0
                    try:
                        orchestrator.checkpoint_session()
                        console.print(f"[{p.fg_faint}]· memory updated[/]")
                    except Exception:
                        pass

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
