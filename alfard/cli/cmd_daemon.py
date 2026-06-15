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
MAX_IPC_CONNECTIONS = 32
PROTOCOL_VERSION = 1

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
# IPC framing — 4-byte big-endian length prefix + JSON body
# ---------------------------------------------------------------------------

def _ipc_write(writer: asyncio.StreamWriter, payload: bytes) -> None:
    writer.write(len(payload).to_bytes(4, "big") + payload)


async def _ipc_read(reader: asyncio.StreamReader, timeout: float) -> bytes | None:
    """Read one length-prefixed message; return None on clean EOF."""
    try:
        header = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
    except asyncio.IncompleteReadError:
        return None
    length = int.from_bytes(header, "big")
    return await asyncio.wait_for(reader.readexactly(length), timeout=timeout)


# ---------------------------------------------------------------------------
# IPC client handler
# ---------------------------------------------------------------------------

async def _handle_ipc_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    queue: asyncio.Queue,
    on_activity,
    agent_name: str,
    conn_sem: asyncio.Semaphore,
) -> None:
    """Accept one length-prefixed JSON request, queue it, return the JSON response.

    Supported commands:
      {"task": "<prompt>"}                              — run a task via the orchestrator lane
      {"cmd": "cron_run", "name": "<job>", "task": "<prompt>"}  — fire a cron job in-process
    """
    if conn_sem.locked():
        try:
            _ipc_write(writer, b'{"error": "too many connections"}')
            await writer.drain()
        except Exception:
            pass
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return

    async with conn_sem:
        try:
            try:
                raw = await _ipc_read(reader, timeout=10.0)
            except asyncio.TimeoutError:
                _ipc_write(writer, b'{"error": "read timeout"}')
                await writer.drain()
                return
            if raw is None:
                return
            try:
                req = json.loads(raw.decode())
            except json.JSONDecodeError:
                _ipc_write(writer, b'{"error": "invalid json"}')
                await writer.drain()
                return

            client_protocol = req.get("protocol")
            if client_protocol is not None and client_protocol != PROTOCOL_VERSION:
                _ipc_write(writer, json.dumps({
                    "error": (
                        f"protocol version mismatch: "
                        f"client={client_protocol} daemon={PROTOCOL_VERSION} — "
                        f"run 'pip install -U alfard' to align versions"
                    )
                }).encode())
                await writer.drain()
                return

            cmd = req.get("cmd")

            if cmd == "reload_env":
                load_env()
                _ipc_write(writer, b'{"result": "reloaded"}')
                await writer.drain()
                return

            if cmd == "get_version":
                from alfard import __version__
                _ipc_write(writer, json.dumps({"version": __version__}).encode())
                await writer.drain()
                return

            if cmd == "cron_run":
                name = req.get("name", "").strip()
                task = req.get("task", "").strip()
                if not name or not task:
                    _ipc_write(writer, b'{"error": "missing name or task"}')
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
                    resp = json.dumps({"result": result if result is not None else "injected"}).encode()
                except asyncio.TimeoutError:
                    resp = b'{"error": "timeout"}'
                except Exception as exc:
                    resp = json.dumps({"error": str(exc)}).encode()
                _ipc_write(writer, resp)
                await writer.drain()
                return

            task = req.get("task", "").strip()
            if not task:
                _ipc_write(writer, b'{"error": "missing task"}')
                await writer.drain()
                return

            on_activity()

            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            try:
                queue.put_nowait((task, fut))
            except asyncio.QueueFull:
                _ipc_write(writer, b'{"error": "server busy - queue full"}')
                await writer.drain()
                return

            try:
                result = await asyncio.wait_for(fut, timeout=300.0)
                resp = json.dumps({"result": result}).encode()
            except asyncio.TimeoutError:
                if not fut.done():
                    fut.cancel()
                resp = b'{"error": "timeout"}'
            except Exception as exc:
                resp = json.dumps({"error": str(exc)}).encode()

            _ipc_write(writer, resp)
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
        def _put() -> None:
            try:
                queue.put_nowait((task, None))
                _log.info("cron '%s' enqueued", job_name)
            except asyncio.QueueFull:
                _log.warning("cron '%s' dropped — queue full", job_name)
        loop.call_soon_threadsafe(_put)

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
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    idle_reset = asyncio.Event()
    shutdown_event = asyncio.Event()
    worker_idle = asyncio.Event()
    worker_idle.set()
    conn_sem = asyncio.Semaphore(MAX_IPC_CONNECTIONS)
    _session_checkpointed = False

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
        ipc_server = await asyncio.start_server(
            lambda r, w: _handle_ipc_client(r, w, queue, on_activity, agent_name, conn_sem),
            "127.0.0.1",
            0,  # OS picks port; sockets[0] is bound before start_server() returns
        )
        _port = ipc_server.sockets[0].getsockname()[1]
        port_file = sock_path.parent / "agent.port"
        _port_bytes = str(_port).encode("utf-8")
        _fd = os.open(str(port_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(_fd, _port_bytes)
        finally:
            os.close(_fd)
        _log.info("IPC TCP server ready: 127.0.0.1:%d", _port)
    else:
        if sock_path.exists():
            sock_path.unlink()
        _old_umask = os.umask(0o177)
        try:
            ipc_server = await asyncio.start_unix_server(
                lambda r, w: _handle_ipc_client(r, w, queue, on_activity, agent_name, conn_sem),
                path=str(sock_path),
            )
        finally:
            os.umask(_old_umask)
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
        nonlocal _session_checkpointed
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(idle_reset.wait(), timeout=float(IDLE_TIMEOUT_SEC))
                idle_reset.clear()
            except asyncio.TimeoutError:
                # Poll with a bounded wait so a hung worker can't block the watchdog forever.
                while not worker_idle.is_set() and not shutdown_event.is_set():
                    try:
                        await asyncio.wait_for(worker_idle.wait(), timeout=30.0)
                    except asyncio.TimeoutError:
                        pass
                if not shutdown_event.is_set():
                    _log.info(
                        "idle timeout (%d min) — checkpointing session before shutdown",
                        IDLE_TIMEOUT_SEC // 60,
                    )
                    try:
                        await loop.run_in_executor(None, orchestrator.checkpoint_session)
                        _session_checkpointed = True
                        _log.info("idle checkpoint complete")
                    except Exception as exc:
                        _log.warning("idle checkpoint failed: %s", exc)
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
                scheduler.shutdown(wait=True)
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
        channel_manager.join_all(timeout=5.0)

        # Drain queue and stop lane worker
        loop.call_soon_threadsafe(queue.put_nowait, None)
        await worker_task

        # Session end + memory write (skip if idle watchdog already checkpointed)
        if not _session_checkpointed:
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

    if sys.platform == "win32":
        import socket as _sprobe
        _port_file = AGENTS_DIR / agent / "agent.port"
        if _port_file.exists():
            try:
                _port = int(_port_file.read_text(encoding="utf-8").strip())
                with _sprobe.socket(_sprobe.AF_INET, _sprobe.SOCK_STREAM) as _s:
                    _s.settimeout(1.0)
                    _s.connect(("127.0.0.1", _port))
                console.print(error_block(
                    agent="alfard daemon",
                    state="failed",
                    headline=f"daemon for '{agent}' is already running.",
                    explanation=f"live on port {_port} — stop the existing daemon first.",
                    next_actions=[
                        {"cmd": f"alfard service stop {agent}", "desc": "stop the running daemon"},
                    ],
                ))
                raise SystemExit(1)
            except (ConnectionRefusedError, OSError, ValueError):
                # Stale port file from a previous crash — remove it so the new daemon
                # can write its own port number without confusion.
                try:
                    _port_file.unlink()
                except OSError:
                    pass
    else:
        _early_sock = AGENTS_DIR / agent / "agent.sock"
        if _early_sock.exists():
            try:
                import socket as _sprobe
                with _sprobe.socket(_sprobe.AF_UNIX, _sprobe.SOCK_STREAM) as _s:
                    _s.settimeout(1.0)
                    _s.connect(str(_early_sock))
                console.print(error_block(
                    agent="alfard daemon",
                    state="failed",
                    headline=f"daemon for '{agent}' is already running.",
                    explanation=f"live socket at {_early_sock} — stop the existing daemon first.",
                    next_actions=[
                        {"cmd": f"alfard service stop {agent}", "desc": "stop the running daemon"},
                    ],
                ))
                raise SystemExit(1)
            except (ConnectionRefusedError, OSError):
                pass  # stale socket — safe to proceed

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
