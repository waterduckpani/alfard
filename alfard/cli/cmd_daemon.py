"""Run an agent as a persistent daemon — channels, cron scheduler, and IPC socket."""

import asyncio
import json
import logging
import os
import signal
import stat
import uuid
from pathlib import Path

import click
from alfard.agents.loader import AgentLoader, list_agents, AGENTS_DIR
from alfard.channels.discord import DiscordChannel
from alfard.channels.manager import ChannelManager
from alfard.channels.slack import SlackChannel
from alfard.channels.telegram import TelegramChannel
from alfard.cli.components import alfard_select, alfard_spinner, error_block
from alfard.cli.help_formatter import AlfardCommand
from alfard.cli.theme import console, p
from alfard.orchestrator.builder import build_orchestrator
from alfard.paths import load_env

IDLE_TIMEOUT_SEC = 3600  # 60 minutes

_log = logging.getLogger("alfard.daemon")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_log_file(agent_name: str) -> logging.Handler:
    log_dir = AGENTS_DIR / agent_name / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / "agent.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    handler.setLevel(logging.DEBUG)
    logging.getLogger("alfard").setLevel(logging.DEBUG)
    logging.getLogger("alfard").addHandler(handler)
    return handler


def _load_agent_crons(agent_name: str) -> list[dict]:
    import yaml
    path = AGENTS_DIR / agent_name / "crons.yaml"
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return [j for j in data.get("jobs", []) if j.get("enabled", True)]


# ---------------------------------------------------------------------------
# Lane worker — one coroutine, sequential processing
# ---------------------------------------------------------------------------

async def _lane_worker(queue: asyncio.Queue, orchestrator) -> None:
    loop = asyncio.get_running_loop()
    while True:
        item = await queue.get()
        if item is None:  # shutdown sentinel
            queue.task_done()
            break
        task, fut = item
        try:
            result = await loop.run_in_executor(None, orchestrator.run, task)
            if fut is not None and not fut.done():
                fut.set_result(result)
        except Exception as exc:
            _log.error("lane worker error: %s", exc, exc_info=True)
            if fut is not None and not fut.done():
                fut.set_exception(exc)
        finally:
            queue.task_done()


# ---------------------------------------------------------------------------
# IPC client handler
# ---------------------------------------------------------------------------

async def _handle_ipc_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    queue: asyncio.Queue,
    on_activity,
) -> None:
    """Accept one JSON-line request, queue it, return the JSON-line response."""
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=10.0)
        if not raw:
            return
        try:
            req = json.loads(raw.decode())
        except json.JSONDecodeError:
            writer.write(b'{"error": "invalid json"}\n')
            await writer.drain()
            return

        task = req.get("task", "").strip()
        if not task:
            writer.write(b'{"error": "missing task"}\n')
            await writer.drain()
            return

        on_activity()

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        await queue.put((task, fut))

        try:
            result = await asyncio.wait_for(asyncio.shield(fut), timeout=300.0)
            resp = json.dumps({"result": result}) + "\n"
        except asyncio.TimeoutError:
            resp = json.dumps({"error": "timeout"}) + "\n"
        except Exception as exc:
            resp = json.dumps({"error": str(exc)}) + "\n"

        writer.write(resp.encode())
        await writer.drain()
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# APScheduler — this agent's crons only
# ---------------------------------------------------------------------------

def _start_crons(
    agent_name: str,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    on_activity,
):
    from alfard.cron.parser import parse_schedule
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    jobs = _load_agent_crons(agent_name)
    if not jobs:
        return None

    scheduler = BackgroundScheduler()

    def _enqueue(task: str, job_name: str) -> None:
        on_activity()
        loop.call_soon_threadsafe(queue.put_nowait, (task, None))
        _log.info("cron '%s' enqueued", job_name)

    loaded = 0
    for job in jobs:
        job_id = f"{agent_name}.{job['name']}"
        try:
            parsed = parse_schedule(job["schedule"])
        except ValueError as exc:
            _log.warning("skipping cron '%s': %s", job_id, exc)
            continue
        trigger = (
            CronTrigger(**parsed["kwargs"])
            if parsed["trigger"] == "cron"
            else IntervalTrigger(**parsed["kwargs"])
        )
        scheduler.add_job(
            _enqueue,
            trigger=trigger,
            id=job_id,
            name=f"{agent_name}: {job['name']}",
            args=[job["task"], job["name"]],
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        loaded += 1

    if loaded == 0:
        return None

    scheduler.start()
    _log.info("cron scheduler: %d job(s) for '%s'", loaded, agent_name)
    return scheduler


# ---------------------------------------------------------------------------
# Main async loop
# ---------------------------------------------------------------------------

async def _run_daemon(
    agent_name: str,
    orchestrator,
    audit,
    channel_manager: ChannelManager,
    sock_path: Path,
) -> None:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    idle_reset = asyncio.Event()
    shutdown_event = asyncio.Event()

    def on_activity() -> None:
        """Reset the idle timer; safe to call from any thread."""
        loop.call_soon_threadsafe(idle_reset.set)

    # Lane worker
    worker_task = asyncio.create_task(_lane_worker(queue, orchestrator))

    # IPC socket
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    ipc_server = await asyncio.start_unix_server(
        lambda r, w: _handle_ipc_client(r, w, queue, on_activity),
        path=str(sock_path),
    )
    os.chmod(sock_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    _log.info("IPC socket ready: %s", sock_path)

    # Cron scheduler
    scheduler = _start_crons(agent_name, queue, loop, on_activity)

    # Channels — same as headless: all run in daemon threads
    channel_manager.start_all(main_channel="__daemon__")

    # SIGTERM → set shutdown event
    def _on_sigterm() -> None:
        _log.info("SIGTERM received — shutting down")
        shutdown_event.set()

    loop.add_signal_handler(signal.SIGTERM, _on_sigterm)

    # Idle watchdog
    async def _watchdog() -> None:
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(idle_reset.wait(), timeout=float(IDLE_TIMEOUT_SEC))
                idle_reset.clear()
            except asyncio.TimeoutError:
                _log.info(
                    "idle timeout (%d min) — triggering session checkpoint",
                    IDLE_TIMEOUT_SEC // 60,
                )
                shutdown_event.set()
                return

    watchdog_task = asyncio.create_task(_watchdog())

    try:
        await shutdown_event.wait()
    finally:
        watchdog_task.cancel()
        loop.remove_signal_handler(signal.SIGTERM)

        if scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass

        ipc_server.close()
        await ipc_server.wait_closed()
        if sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass

        channel_manager.stop_all()

        # Drain queue and stop lane worker
        loop.call_soon_threadsafe(queue.put_nowait, None)
        await worker_task

        # Session end + memory write
        try:
            orchestrator.checkpoint_session()
        except Exception as exc:
            _log.warning("checkpoint_session failed: %s", exc)

        try:
            audit.log_session_end(
                outcome="daemon_shutdown",
                turns=audit._tool_calls_total,
                tool_calls_total=audit._tool_calls_total,
                tool_calls_failed=audit._tool_calls_failed,
                corrections_detected=audit._corrections_detected,
            )
            audit.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------

@click.command(cls=AlfardCommand)
@click.argument("agent", required=False)
@click.option(
    "--no-mcp", is_flag=True, default=False,
    help="Skip MCP server connections (faster startup for testing)",
)
def daemon(agent: str | None, no_mcp: bool) -> None:
    """Run an agent as a persistent daemon with channels, cron, and IPC socket.

    Starts all configured channel listeners (Slack, Telegram, Discord) and the
    cron scheduler for this agent only. Exposes a Unix socket for programmatic
    control. Shuts down cleanly after 60 minutes of inactivity or on SIGTERM/SIGINT.

    \b
    Socket: ~/.alfard/agents/<agent>/agent.sock
    Protocol: newline-delimited JSON
      send:    {"task": "<prompt>"}
      receive: {"result": "<response>"} | {"error": "<message>"}
    \b
    Examples:
      alfard daemon postman
      alfard daemon sahil --no-mcp
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
            agent="alfard daemon",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
            next_actions=[
                {"cmd": "alfard list", "desc": "see available agents"},
                {"cmd": "alfard create", "desc": "create a new one"},
            ],
        ))
        raise SystemExit(1)

    load_env()

    try:
        loader = AgentLoader(agent)
        loader.build_system_prompt()
    except Exception as exc:
        console.print(error_block(
            agent="alfard daemon",
            state="failed",
            headline=f"failed to load agent '{agent}'.",
            explanation=str(exc),
        ))
        raise SystemExit(1)

    log_handler = _setup_log_file(agent)
    session_id = str(uuid.uuid4())

    audit = None
    try:
        with alfard_spinner("connecting integrations...", color="ok"):
            orchestrator, audit, loader, registry = build_orchestrator(
                agent_name=agent,
                connect_mcp=not no_mcp,
                gate_enabled=True,
                session_id=session_id,
            )

        audit.log_session_start(
            agent_name=agent,
            provider=orchestrator._llm.provider_name,
            model=orchestrator._llm.model,
        )

        channel_manager = ChannelManager()
        channel_manager.set_audit(audit)

        if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"):
            channel_manager.register(SlackChannel(agent))
        if os.environ.get("TELEGRAM_BOT_TOKEN"):
            channel_manager.register(TelegramChannel(agent))
        if os.environ.get("DISCORD_BOT_TOKEN"):
            channel_manager.register(DiscordChannel(agent))

        active = channel_manager.names()
        sock_path = AGENTS_DIR / agent / "agent.sock"
        crons = _load_agent_crons(agent)

        if active:
            console.print(f"[{p.fg_dim}]▸ {agent} daemon on: {', '.join(active)}[/]")
        else:
            console.print(f"[{p.fg_dim}]▸ {agent} daemon running (IPC only — no channels)[/]")
        if crons:
            console.print(f"[{p.fg_faint}]cron: {len(crons)} job(s) scheduled[/]")
        console.print(f"[{p.fg_faint}]socket → {sock_path}[/]")
        console.print(f"[{p.fg_faint}]logs   → {AGENTS_DIR / agent / 'logs' / 'agent.log'}[/]")
        console.print(f"[{p.fg_faint}]idle timeout: 60 min · ctrl+c or SIGTERM to stop.[/]\n")

        try:
            asyncio.run(_run_daemon(
                agent_name=agent,
                orchestrator=orchestrator,
                audit=audit,
                channel_manager=channel_manager,
                sock_path=sock_path,
            ))
        except KeyboardInterrupt:
            console.print(f"\n[{p.fg_dim}]stopping...[/]")

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
