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


class _ProposeMemory:
    def __init__(self):
        self._manager = None

    def set_manager(self, manager):
        self._manager = manager

    def __call__(
        self,
        content: str,
        memory_type: str = "fact",
        valence: str = "neutral",
        reason: str = "",
    ) -> str:
        if self._manager:
            return self._manager.write(
                content,
                memory_type=memory_type,
                valence=valence,
                source="agent_inferred",
                reason=reason,
            )
        return "Memory not available."


_propose_memory = _ProposeMemory()


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
        if servers:
            console.print(f"[{p.fg_dim}]connected: {', '.join(servers)}[/]")

        audit.log_session_start(
            agent_name=agent,
            provider=orchestrator._llm.provider_name,
            model=orchestrator._llm.model,
        )

        _propose_memory.set_manager(loader.memory_manager)

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
                        source="user_explicit",
                    )
                    console.print(f"[{p.fg_dim}]{result}[/]\n")
                continue

            audit.log_user_correction(stripped)

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

        # 8. Save memory before exit
        try:
            messages = orchestrator._memory.get_messages()
            turns = [
                m for m in messages
                if m["role"] in ("user", "assistant") and m.get("content")
            ]
            if len(turns) >= 2:
                summary_prompt = (
                    "Summarise this conversation in 2-3 sentences.\n"
                    "Focus on: what was accomplished, what was discussed.\n"
                    "Be specific and concise.\n\n"
                    + "\n".join(
                        f"{m['role'].upper()}: {m['content'][:300]}"
                        for m in turns[-20:]
                    )
                )
                response = orchestrator._llm.complete([
                    {"role": "user", "content": summary_prompt}
                ])
                summary = response.get("content", "").strip()

                all_text = " ".join(
                    m["content"][:100] for m in turns
                    if isinstance(m, dict) and isinstance(m.get("content"), str)
                ).lower()
                topics = []
                for keyword in ["notion", "gmail", "github", "slack",
                                "gdrive", "linear", "stocky", "alfard"]:
                    if keyword in all_text:
                        topics.append(keyword)

                facts_learned = getattr(orchestrator, '_facts_learned', 0)

                if summary:
                    loader.memory_manager.save_session(
                        summary=summary,
                        topics=topics,
                        turns=len(turns) // 2,
                        facts_learned=facts_learned,
                    )
        except Exception as e:
            console.print(
                f"[{p.fg_faint}]note: could not save session memory: {e}[/]"
            )
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
