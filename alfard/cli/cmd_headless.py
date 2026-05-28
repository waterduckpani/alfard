"""Run an agent headless — all channels active, no terminal UI."""

import logging
import os
import signal
import threading
import uuid

import click
from alfard.cli.help_formatter import AlfardCommand
from alfard.agents.loader import AgentLoader, list_agents, AGENTS_DIR
from alfard.orchestrator.builder import build_orchestrator
from alfard.cli.theme import p, console
from alfard.cli.components import error_block, alfard_spinner, alfard_select
from alfard.channels.manager import ChannelManager
from alfard.channels.slack import SlackChannel
from alfard.channels.telegram import TelegramChannel
from alfard.channels.discord import DiscordChannel


def _has_headless_channels() -> bool:
    """Return True if at least one headless channel token is configured."""
    from alfard.paths import load_env
    load_env()
    has_slack = bool(
        os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN")
    )
    has_telegram = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
    has_discord = bool(os.environ.get("DISCORD_BOT_TOKEN"))
    return has_slack or has_telegram or has_discord


def _setup_log_file(agent_name: str) -> logging.Handler:
    """Configure file logging for headless mode and return the handler."""
    log_dir = AGENTS_DIR / agent_name / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "agent.log"

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    handler.setLevel(logging.DEBUG)

    root = logging.getLogger("alfard")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

    return handler


@click.command(cls=AlfardCommand)
@click.argument("agent", required=False)
@click.option("--no-mcp", is_flag=True, default=False,
              help="Skip MCP server connections (faster startup for testing)")
def headless(agent: str | None, no_mcp: bool) -> None:
    """Run an agent on all connected channels with no terminal UI.

    Designed for running as a background service or in a screen session.
    Terminal input/output is suppressed — interaction happens via Slack,
    Telegram, Discord, or other connected channels.

    \b
    Examples:
      alfard headless postman
      alfard headless sahil --no-mcp
    """
    if not agent:
        agents = list_agents()
        if not agents:
            console.print(f"[{p.fg_faint}]no agents found. run alfard create first.[/]")
            return
        agent = alfard_select("which agent?", agents)
        if not agent:
            return

    if agent not in list_agents():
        console.print(error_block(
            agent="alfard headless",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
            next_actions=[
                {"cmd": "alfard list", "desc": "see available agents"},
                {"cmd": "alfard create", "desc": "create a new one"},
            ],
        ))
        raise SystemExit(1)

    from alfard.paths import load_env
    load_env()

    if not _has_headless_channels():
        console.print(
            f"\n[{p.err}]no channels configured.[/]\n"
            f"[{p.fg_dim}]run [{p.fg_em}]alfard channel connect[/][{p.fg_dim}] to add Slack, "
            f"Telegram, or Discord before running headless.[/]\n"
        )
        raise SystemExit(1)

    try:
        loader = AgentLoader(agent)
        loader.build_system_prompt()
    except Exception as e:
        console.print(error_block(
            agent="alfard headless",
            state="failed",
            headline=f"failed to load agent '{agent}'.",
            explanation=str(e),
        ))
        raise SystemExit(1)

    log_handler = _setup_log_file(agent)
    session_id = str(uuid.uuid4())

    orchestrator = None
    audit = None
    try:
        with alfard_spinner("connecting integrations...", color="ok") as _s:
            orchestrator, audit, loader, registry = build_orchestrator(
                agent_name=agent,
                connect_mcp=not no_mcp,
                gate_enabled=True,
                session_id=session_id,
            )

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

        channel_manager = ChannelManager()
        channel_manager.set_audit(audit)

        from alfard.paths import load_env
        load_env()
        if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"):
            channel_manager.register(SlackChannel(agent))
        if os.environ.get("TELEGRAM_BOT_TOKEN"):
            channel_manager.register(TelegramChannel(agent))
        if os.environ.get("DISCORD_BOT_TOKEN"):
            channel_manager.register(DiscordChannel(agent))

        active = channel_manager.names()
        console.print(f"[{p.fg_dim}]▸ {agent} running headless on: {', '.join(active)}[/]")
        console.print(f"[{p.fg_faint}]logs → {AGENTS_DIR / agent / 'logs' / 'agent.log'}[/]")
        console.print(f"[{p.fg_faint}]ctrl+c to stop.[/]\n")

        stop_event = threading.Event()

        def _sigterm_handler(signum, frame):
            logging.getLogger("alfard.headless").info("SIGTERM received — stopping")
            channel_manager.stop_all()
            stop_event.set()

        if sys.platform != "win32":
            signal.signal(signal.SIGTERM, _sigterm_handler)
        if sys.platform == "win32":
            try:
                signal.signal(signal.SIGBREAK, _sigterm_handler)
            except AttributeError:
                pass

        # All channels run as daemon threads; main thread just waits.
        channel_manager.start_all(main_channel="__headless__")

        try:
            stop_event.wait()
        except KeyboardInterrupt:
            console.print(f"\n[{p.fg_dim}]stopping...[/]")
            channel_manager.stop_all()

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
    finally:
        logging.getLogger("alfard").removeHandler(log_handler)
        log_handler.close()
