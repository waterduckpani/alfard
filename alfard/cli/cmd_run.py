"""Starts a named agent and enters its interactive ReAct loop."""

import click
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown
from alfard.agents.loader import AgentLoader, list_agents
from alfard.orchestrator.builder import build_orchestrator
from alfard.cli import theme

console = Console()


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


@click.command()
@click.argument("agent")
@click.option("--no-mcp", is_flag=True, default=False,
              help="Skip MCP server connections (faster startup for testing)")
def run(agent: str, no_mcp: bool) -> None:
    """Start a chat session with an agent.

    AGENT is the name of the agent to run.

    Example:
      alfard run postman
    """

    # 1. Validate agent exists
    if agent not in list_agents():
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]\n\n"
            f"Run [bold {theme.PRIMARY}]alfard list[/bold {theme.PRIMARY}] to see available agents.\n"
            f"Run [bold {theme.PRIMARY}]alfard create[/bold {theme.PRIMARY}] to create a new one.",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)

    # 2. Load agent
    try:
        loader = AgentLoader(agent)
        system_prompt = loader.build_system_prompt()
    except Exception as e:
        console.print(Panel(
            f"[{theme.ERROR}]Failed to load agent '{agent}': {e}[/{theme.ERROR}]",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)

    # 3. Print startup banner
    soul_path = loader.agent_dir / "soul.md"
    first_line = ""
    if soul_path.exists():
        for line in soul_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                first_line = stripped[:80]
                break

    console.print(Panel(
        f"[bold {theme.PRIMARY}]{agent}[/bold {theme.PRIMARY}]\n[{theme.DIM}]{first_line or 'Ready'}[/{theme.DIM}]",
        title="alfard",
        border_style=theme.BORDER,
        padding=(0, 2)
    ))

    audit = None
    try:
        with console.status("[dim]Connecting integrations...[/dim]"):
            orchestrator, audit, loader, registry = build_orchestrator(
                agent_name=agent,
                connect_mcp=not no_mcp,
                gate_enabled=True,
            )

        connected = [
            name for name, info in orchestrator._registry._tools.items()
            if info.get("is_mcp") and "." in name
        ]
        servers = sorted(set(n.split(".")[0] for n in connected))
        if servers:
            console.print(f"[{theme.DIM}]Connected: {', '.join(servers)}[/{theme.DIM}]")

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

        # 7. Interactive chat loop
        console.print(
            f"\n[{theme.DIM}]Type your message and press Enter. "
            f"Type [bold]exit[/bold] or [bold]quit[/bold] to stop.[/{theme.DIM}]\n"
        )

        first_message = True

        while True:
            try:
                user_input = Prompt.ask(f"[bold {theme.PRIMARY}]you[/bold {theme.PRIMARY}]")
            except (KeyboardInterrupt, EOFError):
                console.print(f"\n[{theme.DIM}]Goodbye.[/{theme.DIM}]")
                break

            if user_input.strip().lower() in ("exit", "quit", "q"):
                console.print(f"[{theme.DIM}]Goodbye.[/{theme.DIM}]")
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
                console.print(f"[bold]{agent}[/bold]")
                console.print(Markdown(response))
                console.print()
            except KeyboardInterrupt:
                console.print(f"\n[{theme.DIM}]Interrupted.[/{theme.DIM}]\n")
                orchestrator.reset()
                continue
            except Exception as e:
                console.print(Panel(
                    f"[{theme.ERROR}]Error: {e}[/{theme.ERROR}]",
                    border_style=theme.PANEL_ERROR
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
                f"[dim]Note: could not save session memory: {e}[/dim]"
            )
    finally:
        if audit is not None:
            audit.close()
