"""Run an agent as a persistent daemon — channels, cron scheduler, and IPC socket."""

import asyncio
import json
import logging
import os
import signal
import stat
import sys
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
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [j for j in data.get("jobs", []) if j.get("enabled", True)]


# ---------------------------------------------------------------------------
# Lane worker — one coroutine, sequential processing
# ---------------------------------------------------------------------------

async def _lane_worker(queue: asyncio.Queue, orchestrator, worker_idle: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    while True:
        item = await queue.get()
        if item is None:  # shutdown sentinel
            queue.task_done()
            break
        task, fut = item
        worker_idle.clear()
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
            worker_idle.set()


# ---------------------------------------------------------------------------
# IPC client handler
# ---------------------------------------------------------------------------

async def _handle_ipc_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    queue: asyncio.Queue,
    on_activity,
    agent_name: str,
) -> None:
    """Accept one JSON-line request, queue it, return the JSON-line response.

    Supported commands:
      {"task": "<prompt>"}                              — run a task via the orchestrator lane
      {"cmd": "cron_run", "name": "<job>", "task": "<prompt>"}  — fire a cron job in-process
    """
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

        cmd = req.get("cmd")

        if cmd == "reload_env":
            load_env()
            writer.write(b'{"result": "reloaded"}\n')
            await writer.drain()
            return

        if cmd == "get_version":
            from alfard import __version__
            writer.write((json.dumps({"version": __version__}) + "\n").encode())
            await writer.drain()
            return

        if cmd == "cron_run":
            name = req.get("name", "").strip()
            task = req.get("task", "").strip()
            if not name or not task:
                writer.write(b'{"error": "missing name or task"}\n')
                await writer.drain()
                return
            on_activity()
            loop = asyncio.get_running_loop()
            try:
                from alfard.cron.scheduler import _fire_cron_job
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, _fire_cron_job, agent_name, name, task),
                    timeout=300.0,
                )
                resp = json.dumps({"result": result if result is not None else "injected"}) + "\n"
            except asyncio.TimeoutError:
                resp = json.dumps({"error": "timeout"}) + "\n"
            except Exception as exc:
                resp = json.dumps({"error": str(exc)}) + "\n"
            writer.write(resp.encode())
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
# Upgrade version check — runs once after channels start
# ---------------------------------------------------------------------------

def _do_version_check(agent_name: str, channel_manager: ChannelManager) -> None:
    """Compare installed vs in-process version; warn via alive channel if they differ."""
    try:
        from importlib.metadata import version as _pkg_version, PackageNotFoundError
        import alfard
        try:
            installed = _pkg_version("alfard")
        except PackageNotFoundError:
            return
        running = getattr(alfard, "__version__", None)
        if running is None or running == "unknown" or installed == running:
            return
        msg = (
            f"⚠️ Alfard was upgraded to v{installed} while running v{running}. "
            f"Restart to apply the update: alfard service restart {agent_name}"
        )
        _log.warning("version mismatch: running=%s installed=%s", running, installed)
        channel_manager._send_to_alive_channel("__version_check__", msg)
    except Exception:
        pass


async def _version_check_async(agent_name: str, channel_manager: ChannelManager) -> None:
    """One-shot coroutine: detect post-upgrade version mismatch with a 5 s hard timeout."""
    try:
        loop = asyncio.get_running_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, _do_version_check, agent_name, channel_manager),
            timeout=5.0,
        )
    except Exception:
        pass


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
    worker_idle = asyncio.Event()
    worker_idle.set()

    def on_activity() -> None:
        """Reset the idle timer; safe to call from any thread."""
        loop.call_soon_threadsafe(idle_reset.set)

    # Lane worker
    worker_task = asyncio.create_task(_lane_worker(queue, orchestrator, worker_idle))

    # IPC socket / TCP server
    sock_path = sock_path.resolve()
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    port_file: Path | None = None

    if sys.platform == "win32":
        import socket as _socket
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _s:
            _s.bind(("127.0.0.1", 0))
            _port = _s.getsockname()[1]
        ipc_server = await asyncio.start_server(
            lambda r, w: _handle_ipc_client(r, w, queue, on_activity, agent_name),
            "127.0.0.1",
            _port,
        )
        port_file = sock_path.parent / "agent.port"
        port_file.write_text(str(_port), encoding="utf-8")
        _log.info("IPC TCP server ready: 127.0.0.1:%d", _port)
    else:
        if sock_path.exists():
            sock_path.unlink()
        ipc_server = await asyncio.start_unix_server(
            lambda r, w: _handle_ipc_client(r, w, queue, on_activity, agent_name),
            path=str(sock_path),
        )
        os.chmod(sock_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        _log.info("IPC socket ready: %s", sock_path)

    # Cron scheduler
    scheduler = _start_crons(agent_name, queue, loop, on_activity)

    # Channels — same as headless: all run in daemon threads
    channel_manager.start_all(main_channel="__daemon__")

    # One-shot version check — detects post-upgrade stale daemon (runs once, ≤5 s)
    asyncio.create_task(_version_check_async(agent_name, channel_manager))

    # Signal handling — platform-aware
    if sys.platform == "win32":
        import signal as _signal
        def _win_shutdown(*_) -> None:
            shutdown_event.set()
        _signal.signal(_signal.SIGINT, _win_shutdown)
        try:
            _signal.signal(_signal.SIGBREAK, _win_shutdown)
        except AttributeError:
            pass
    else:
        def _on_sigterm() -> None:
            _log.info("SIGTERM received — shutting down")
            shutdown_event.set()
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
        loop.add_signal_handler(signal.SIGINT, shutdown_event.set)

    # Idle watchdog
    async def _watchdog() -> None:
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(idle_reset.wait(), timeout=float(IDLE_TIMEOUT_SEC))
                idle_reset.clear()
            except asyncio.TimeoutError:
                await worker_idle.wait()  # don't interrupt a running task
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
        if sys.platform != "win32":
            loop.remove_signal_handler(signal.SIGTERM)
            loop.remove_signal_handler(signal.SIGINT)

        if scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
            except Exception:
                pass

        ipc_server.close()
        await ipc_server.wait_closed()
        if sys.platform != "win32" and sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass
        if port_file is not None and port_file.exists():
            try:
                port_file.unlink()
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
