"""Starts a named agent and enters its interactive ReAct loop."""

import sys
import uuid
import click
from alfard.cli.help_formatter import AlfardCommand
from datetime import datetime
from rich.prompt import Prompt
from rich.markdown import Markdown
from alfard.agents.loader import AgentLoader, list_agents
from alfard.orchestrator.builder import build_orchestrator
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, error_block, alfard_spinner, alfard_select


_EXPLICIT_PHRASES = (
    "remember that",
    "don't forget",
    "never forget",
    "always remember",
    "make sure you remember",
)


class _ProposeMemory:
    def __init__(self):
        self._manager = None
        self._last_user_message = ""

    def set_manager(self, manager):
        self._manager = manager

    def set_user_message(self, msg: str) -> None:
        self._last_user_message = msg

    def __call__(
        self,
        content: str,
        memory_type: str = "fact",
        valence: str = "neutral",
        reason: str = "",
    ) -> str:
        if not self._manager:
            return "Memory not available."

        source = "agent_inferred"
        confidence = None
        lower_msg = self._last_user_message.lower()
        if any(phrase in lower_msg for phrase in _EXPLICIT_PHRASES):
            source = "user_explicit"
            confidence = 1.0

        result = self._manager.write(
            content,
            memory_type=memory_type,
            valence=valence,
            source=source,
            confidence=confidence,
            reason=reason,
        )

        if result == "conflict":
            return "Memory saved but conflicts with an existing entry — both are marked disputed. Tell the user."
        if result == "duplicate":
            return "Already known. Nothing written."
        if result.startswith("blocked"):
            return "Blocked — content looks like a secret. Nothing written."
        return result


_propose_memory = _ProposeMemory()


class _CompleteGoal:
    def __init__(self):
        self._manager = None

    def set_manager(self, manager):
        self._manager = manager

    def __call__(self, query: str) -> str:
        if self._manager:
            result = self._manager.complete_goal(query)
            return f"completed: {result}" if result else "no matching goal found"
        return "Memory not available."


_complete_goal = _CompleteGoal()


@click.command(cls=AlfardCommand)
@click.argument("agent", required=False)
@click.option("--no-mcp", is_flag=True, default=False,
              help="Skip MCP server connections (faster startup for testing)")
def run(agent: str | None, no_mcp: bool) -> None:
    """Start a chat session with an agent.

    AGENT is the name of the agent to run.

    Example:
      alfard run postman
    """

    if not agent:
        agents = list_agents()
        if not agents:
            console.print(
                f"[{p.fg_faint}]no agents found. run alfard create first.[/]"
            )
            return
        agent = alfard_select("which agent?", agents)
        if not agent:
            return

    if agent not in list_agents():
        console.print(error_block(
            agent="alfard run",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
            next_actions=[
                {"cmd": "alfard list", "desc": "see available agents"},
                {"cmd": "alfard create", "desc": "create a new one"},
            ],
        ))
        raise SystemExit(1)

    try:
        loader = AgentLoader(agent)
        system_prompt = loader.build_system_prompt()
    except Exception as e:
        console.print(error_block(
            agent="alfard run",
            state="failed",
            headline=f"failed to load agent '{agent}'.",
            explanation=str(e),
        ))
        raise SystemExit(1)

    soul_path = loader.agent_dir / "soul.md"
    first_line = ""
    if soul_path.exists():
        for line in soul_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                first_line = stripped[:80]
                break

    console.print(f"\n[{p.fg_em}]{agent}[/]  [{p.fg_faint}]·[/]  [{p.fg_dim}]{first_line or 'ready'}[/]\n")

    session_id = str(uuid.uuid4())
    _turns = 0
    _outcome = "abandoned"

    orchestrator = None
    loader = None
    audit = None
    try:
        try:
            with alfard_spinner("connecting integrations...", color="ok") as _s:
                orchestrator, audit, loader, registry = build_orchestrator(
                    agent_name=agent,
                    connect_mcp=not no_mcp,
                    gate_enabled=True,
                    session_id=session_id,
                )
        except RuntimeError as e:
            msg = str(e)
            if "requires env var" in msg and "is not set" in msg:
                import re
                m = re.search(r"env var '([^']+)'", msg)
                var = m.group(1) if m else "the required API key"
                console.print(error_block(
                    agent="alfard run",
                    state="failed",
                    headline="missing API key.",
                    explanation=f"{var} is not set. add it to your .env file.",
                    next_actions=[
                        {"cmd": f"echo '{var}=your_key' >> .env", "desc": "add the key"},
                        {"cmd": "alfard setup", "desc": "re-run setup to reconfigure"},
                    ],
                ))
                raise SystemExit(1)
            raise

        connected = [
            name for name, info in orchestrator._registry._tools.items()
            if info.get("is_mcp") and "." in name
        ]
        servers = sorted(set(n.split(".")[0] for n in connected))
        if orchestrator._web_access_enabled:
            servers = sorted(servers + ["web search"])
        if servers:
            console.print(f"[{p.fg_dim}]connected: {', '.join(servers)}[/]")

        audit.log_session_start(
            agent_name=agent,
            provider=orchestrator._llm.provider_name,
            model=orchestrator._llm.model,
        )

        _propose_memory.set_manager(loader.memory_manager)
        _complete_goal.set_manager(loader.memory_manager)

        session_count = loader.memory_manager.get_session_count()
        loader.memory_manager.mark_stale_goals(session_count)
        loader.memory_manager.archive_old_memories()
        loader.memory_manager.enforce_caps()

        registry.register(
            "propose_memory",
            "Store a permanent memory mid-session. Call when the user states a "
            "preference, corrects you, shares something worth remembering, or "
            "when you infer something durable about their context or goals.",
            _propose_memory,
            True,
            {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The memory to store"
                    },
                    "memory_type": {
                        "type": "string",
                        "description": "Category: fact, preference, project_state, correction, or goal",
                        "default": "fact"
                    },
                    "valence": {
                        "type": "string",
                        "description": "Sentiment: positive, negative, or neutral",
                        "default": "neutral"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this is worth remembering"
                    }
                },
                "required": ["content"]
            },
            is_mcp=True
        )

        registry.register(
            "complete_goal",
            "Mark an active goal as complete. Call when the user signals a goal has "
            "been achieved — e.g. 'we're done', 'that's shipped', 'finished', "
            "'completed'. Matches the closest goal by semantic similarity.",
            _complete_goal,
            True,
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Description of what was just completed"
                    }
                },
                "required": ["query"]
            },
            is_mcp=True
        )

        console.print(
            f"[{p.fg_faint}]type your message and press enter. type exit or quit to stop.[/]\n"
        )

        first_message = True

        while True:
            try:
                user_input = Prompt.ask(f"[{p.fg_em}]you[/]")
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
                continue

            audit.log_user_correction(stripped)
            _propose_memory.set_user_message(stripped)

            if first_message:
                system_prompt = loader.build_system_prompt(query=stripped)
                orchestrator._memory._system_prompt = system_prompt
                first_message = False

            try:
                console.print()
                response = orchestrator.run(stripped)
                _turns += 1
                console.print(f"[{p.fg_em}]{agent}[/]")
                console.print(Markdown(response))
                console.print()
            except KeyboardInterrupt:
                console.print(f"\n[{p.fg_dim}]interrupted.[/]\n")
                orchestrator.reset()
                continue
            except Exception as e:
                console.print(error_block(
                    agent=agent,
                    state="failed",
                    headline=str(e),
                    explanation="",
                ))
                continue

    finally:
        if audit is not None:
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

        if orchestrator is not None and loader is not None and _turns > 0:
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
