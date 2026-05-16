"""Starts a named agent and enters its interactive ReAct loop."""

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown
from alfard.agents.loader import AgentLoader, list_agents
from alfard.llm.client import LLMClient
from alfard.tools.registry import ToolRegistry
from alfard.audit.logger import AuditLogger
from alfard.gate.approval import ApprovalGate
from alfard.sandbox.executor import SandboxExecutor
from alfard.integrations.credentials import CredentialsManager
from alfard.integrations.mcp_client import MCPClient
from alfard.orchestrator.orchestrator import Orchestrator
from alfard.cli import theme

console = Console()


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

    # 4. Wire up all components
    registry = ToolRegistry()
    audit = AuditLogger()
    try:
        gate = ApprovalGate(audit_logger=audit)
        sandbox = SandboxExecutor()
        credentials = CredentialsManager()

        # 5. Connect MCP servers unless --no-mcp
        if not no_mcp:
            console.print(f"[{theme.DIM}]Connecting integrations...[/{theme.DIM}]")
            mcp = MCPClient(registry)
            mcp.connect_all()
            connected = mcp.list_connected()
            if connected:
                console.print(f"[{theme.DIM}]Connected: {', '.join(connected)}[/{theme.DIM}]")
        else:
            console.print(f"[{theme.DIM}]MCP skipped (--no-mcp)[/{theme.DIM}]")

        # Register gws-based tools if Gmail is configured
        import shutil
        from pathlib import Path
        from alfard.integrations.gws_tools import register_gmail_tools
        gws_creds = Path.home() / ".config" / "gws" / "credentials.enc"
        if shutil.which("gws") and gws_creds.exists():
            register_gmail_tools(registry)
            console.print(f"[{theme.DIM}]Gmail tools registered.[/{theme.DIM}]")

        # 6. Build orchestrator
        orchestrator = Orchestrator(
            llm=LLMClient(),
            registry=registry,
            audit=audit,
            gate=gate,
            sandbox=sandbox,
            credentials=credentials,
            system_prompt=system_prompt,
        )

        # 7. Interactive chat loop
        console.print(
            f"\n[{theme.DIM}]Type your message and press Enter. "
            f"Type [bold]exit[/bold] or [bold]quit[/bold] to stop.[/{theme.DIM}]\n"
        )

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
            if len(messages) > 1:
                memory_lines = []
                for msg in messages:
                    if msg["role"] in ("user", "assistant") and msg.get("content"):
                        role = "You" if msg["role"] == "user" else agent
                        memory_lines.append(f"**{role}**: {msg['content'][:200]}")
                if memory_lines:
                    loader.save_memory("\n".join(memory_lines[-20:]))
        except Exception:
            pass
    finally:
        audit.close()
