"""Starts a named agent and enters its interactive ReAct loop."""

import click
from alfard.cli.help_formatter import AlfardCommand
from datetime import datetime
from rich.prompt import Prompt
from rich.markdown import Markdown
from alfard.agents.loader import AgentLoader, list_agents
from alfard.orchestrator.builder import build_orchestrator
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, error_block, alfard_spinner, alfard_select


class _WriteBrainFact:
    def __init__(self):
        self._manager = None

    def set_manager(self, manager):
        self._manager = manager

    def __call__(self, fact: str, tags: str = "") -> str:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if self._manager:
            return self._manager.store_fact(fact, tag_list)
        return "Memory not available."


_write_brain_fact = _WriteBrainFact()


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

    audit = None
    try:
        try:
            with alfard_spinner("connecting integrations...", color="ok") as _s:
                orchestrator, audit, loader, registry = build_orchestrator(
                    agent_name=agent,
                    connect_mcp=not no_mcp,
                    gate_enabled=True,
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

        _write_brain_fact.set_manager(loader.memory_manager)

        registry.register(
            "write_brain_fact",
            "Store a permanent fact about the user or their work. "
            "Call when user states a preference, corrects you, or "
            "shares something worth remembering.",
            _write_brain_fact,
            True,
            {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "The fact to remember"
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated keywords"
                    }
                },
                "required": ["fact"]
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

            if user_input.strip().lower() in ("exit", "quit", "q"):
                console.print(f"[{p.fg_dim}]goodbye.[/]")
                break

            if not user_input.strip():
                continue

            if first_message:
                system_prompt = loader.build_system_prompt(query=user_input)
                orchestrator._memory._system_prompt = system_prompt
                first_message = False

            try:
                console.print()
                response = orchestrator.run(user_input)
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
            audit.close()
