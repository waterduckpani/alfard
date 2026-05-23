"""Starts a named agent and enters its interactive ReAct loop."""

import os
import sys
import uuid

import click
from alfard.cli.help_formatter import AlfardCommand
from alfard.agents.loader import AgentLoader, list_agents
from alfard.orchestrator.builder import build_orchestrator
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, error_block, alfard_spinner, alfard_select, alfard_input
from alfard.channels.manager import ChannelManager
from alfard.channels.terminal import TerminalChannel
from alfard.channels.slack import SlackChannel
from alfard.channels.telegram import TelegramChannel
from alfard.channels.discord import DiscordChannel


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
        loader.build_system_prompt()
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

    orchestrator = None
    audit = None
    try:
        for _attempt in range(2):
            try:
                with alfard_spinner("connecting integrations...", color="ok") as _s:
                    orchestrator, audit, loader, registry = build_orchestrator(
                        agent_name=agent,
                        connect_mcp=not no_mcp,
                        gate_enabled=True,
                        session_id=session_id,
                    )
                break
            except RuntimeError as e:
                msg = str(e)
                if _attempt == 0 and "requires env var" in msg and "is not set" in msg:
                    import re as _re
                    _m = _re.search(r"env var '([^']+)'", msg)
                    var = _m.group(1) if _m else None
                    if var:
                        console.print(
                            f"\n[{p.warn}]missing API key[/]  "
                            f"[{p.fg_dim}]{var} is not set.[/]"
                        )
                        console.print(
                            f"[{p.fg_faint}]enter a key to continue, "
                            f"or leave blank to go back.[/]\n"
                        )
                        key = alfard_input(var, password=True).strip()
                        if key:
                            os.environ[var] = key
                            from alfard.security.keystore import (
                                write_env_encrypted, decrypt_env,
                            )
                            from alfard.paths import ALFARD_HOME as _HOME
                            try:
                                _existing = decrypt_env(_HOME)
                            except Exception:
                                _existing = {}
                            _existing[var] = key
                            write_env_encrypted(_HOME, _existing)
                            continue
                        console.print(
                            f"\n[{p.fg_dim}]a key is required to run this provider.[/]"
                        )
                        console.print(
                            f"[{p.fg_faint}]run [bold]alfard setup[/bold] "
                            f"to select a different provider.[/]"
                        )
                        raise SystemExit(1)
                raise

        tool_names = set(orchestrator._registry._tools.keys())
        mcp_dotted = [
            name for name, info in orchestrator._registry._tools.items()
            if info.get("is_mcp") and "." in name
        ]
        servers: list[str] = sorted(set(n.split(".")[0] for n in mcp_dotted))
        if any(n.startswith("gmail_") for n in tool_names):
            servers = sorted(servers + ["gmail"])
        if any(n.startswith("gdrive_") for n in tool_names):
            servers = sorted(servers + ["gdrive"])
        if orchestrator._web_access_enabled:
            servers = sorted(servers + ["web search"])
        if servers:
            console.print(f"[{p.fg_dim}]connected: {', '.join(servers)}[/]")

        audit.log_session_start(
            agent_name=agent,
            provider=orchestrator._llm.provider_name,
            model=orchestrator._llm.model,
        )

        # Build channels
        channel_manager = ChannelManager()
        channel_manager.set_audit(audit)

        terminal = TerminalChannel(agent, orchestrator, audit, loader, registry)
        channel_manager.register(terminal)

        from alfard.paths import load_env
        load_env()
        if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"):
            channel_manager.register(SlackChannel(agent))
        if os.environ.get("TELEGRAM_BOT_TOKEN"):
            channel_manager.register(TelegramChannel(agent))
        if os.environ.get("DISCORD_BOT_TOKEN"):
            channel_manager.register(DiscordChannel(agent))

        active = channel_manager.names()
        console.print(f"[{p.fg_dim}]▸ {agent} running on: {', '.join(active)}[/]\n")

        channel_manager.start_all(main_channel="terminal")

    except SystemExit:
        raise
    except Exception as exc:
        if audit is not None:
            try:
                audit._write({"type": "startup_error", "error": str(exc)})
                audit.close()
            except Exception:
                pass
        raise
