"""Starts a named agent and enters its interactive ReAct loop."""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import click
from alfard.cli.help_formatter import AlfardCommand
from alfard.agents.loader import AgentLoader, list_agents, AGENTS_DIR
from alfard.orchestrator.builder import build_orchestrator
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, error_block, alfard_spinner, alfard_select, alfard_input
from alfard.channels.terminal import TerminalChannel


# ---------------------------------------------------------------------------
# IPC helpers
# ---------------------------------------------------------------------------

def _socket_alive(sock_path: Path) -> bool:
    """Return True if the daemon socket exists and accepts connections."""
    import socket as _socket
    import sys

    if sys.platform == "win32":
        port_file = sock_path.parent / "agent.port"
        if not port_file.exists():
            return False
        try:
            port = int(port_file.read_text(encoding="utf-8").strip())
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except (OSError, ValueError):
            return False

    if not sock_path.exists():
        return False
    try:
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(str(sock_path))
        s.close()
        return True
    except OSError:
        return False


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


PROTOCOL_VERSION = 1
_IPC_MAX_RETRIES = 3


async def _ipc_send_with_retry(sock_path: Path, task: str, timeout: float = 300.0) -> str:
    """Attempt _ipc_send up to _IPC_MAX_RETRIES times, sleeping 1 s between OSError failures."""
    for attempt in range(_IPC_MAX_RETRIES):
        try:
            return await _ipc_send(sock_path, task, timeout=timeout)
        except OSError:
            if attempt == _IPC_MAX_RETRIES - 1:
                raise
            await asyncio.sleep(1.0)
    raise RuntimeError("unreachable")  # never reached


async def _ipc_send(sock_path: Path, task: str, timeout: float = 300.0) -> str:
    """Send one task to the daemon and return its response text."""
    if sys.platform == "win32":
        port_file = sock_path.parent / "agent.port"
        port = int(port_file.read_text(encoding="utf-8").strip())
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
    else:
        reader, writer = await asyncio.open_unix_connection(str(sock_path))

    try:
        _ipc_write(writer, json.dumps({"task": task, "protocol": PROTOCOL_VERSION}).encode())
        await writer.drain()
        raw = await _ipc_read(reader, timeout=timeout)
        if raw is None:
            raise RuntimeError("daemon closed connection without response")
        try:
            resp = json.loads(raw.decode())
        except json.JSONDecodeError:
            raise RuntimeError("invalid response from daemon") from None
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp.get("result", "")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _run_ipc_session(agent: str, sock_path: Path) -> None:
    """Interactive terminal session routed through the daemon IPC socket."""
    from rich.markdown import Markdown
    from alfard.channels.terminal import _ChatUI, _rich_to_ansi, _QUIT
    from alfard.gate.approval import QueueNotifier

    notifier = QueueNotifier()
    ui = _ChatUI(agent, notifier)

    ui.append(_rich_to_ansi(
        f"[{p.fg_faint}]type your message and press enter. "
        f"type exit or quit to stop.[/]\n"
        f"[{p.fg_dim}]connected to live daemon · channels and crons active.[/]\n"
    ))

    async def _input_loop() -> None:
        while True:
            raw = await ui.input_queue.get()

            if raw == _QUIT:
                ui.append(_rich_to_ansi(f"[{p.fg_dim}]goodbye.[/]\n"))
                await asyncio.sleep(0.15)
                ui.exit()
                return

            stripped = raw.strip()
            if stripped.lower() in ("exit", "quit", "q", "bye", "done"):
                ui.append(_rich_to_ansi(f"[{p.fg_dim}]goodbye.[/]\n"))
                await asyncio.sleep(0.15)
                ui.exit()
                return
            if not stripped:
                continue

            ui.append(_rich_to_ansi(f"[bold {p.fg_em}]you[/]\n"))
            ui.append(stripped + "\n\n")
            ui.set_running(True)

            try:
                result = await _ipc_send_with_retry(sock_path, stripped)
                ui.append(_rich_to_ansi(f"[{p.fg_em}]{agent}[/]"))
                ui.append(_rich_to_ansi(Markdown(result)))
                ui.append("\n")
            except RuntimeError as exc:
                ui.append(_rich_to_ansi(f"[{p.err}]error: {exc}[/]\n"))
            except asyncio.TimeoutError:
                ui.append(_rich_to_ansi(f"[{p.warn}]timed out waiting for response.[/]\n"))
            except OSError as exc:
                ui.append(_rich_to_ansi(
                    f"[{p.err}]daemon unreachable after {_IPC_MAX_RETRIES} "
                    f"reconnect attempt(s): {exc}[/]\n"
                ))
                ui.append(_rich_to_ansi(f"[{p.fg_dim}]goodbye.[/]\n"))
                await asyncio.sleep(0.15)
                ui.exit()
                return
            finally:
                ui.set_running(False)

    app_task = asyncio.create_task(ui.run_async())
    inp_task = asyncio.create_task(_input_loop())

    done, pending = await asyncio.wait(
        {app_task, inp_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass


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

    console.print(f"[{p.fg_em}]{agent}[/]  [{p.fg_faint}]·[/]  [{p.fg_dim}]{first_line or 'ready'}[/]\n")

    sock_path = (AGENTS_DIR / agent / "agent.sock").resolve()
    if _socket_alive(sock_path):
        asyncio.run(_run_ipc_session(agent, sock_path))
        return

    console.print(
        f"[{p.warn}]⚠[/] [{p.fg_dim}]Agent is not running as a service. "
        f"Channels and crons inactive.[/]\n"
        f"  [{p.fg_faint}]Run: [bold]alfard service install {agent}[/bold][/]\n"
    )

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

        terminal = TerminalChannel(agent, orchestrator, audit, loader, registry)
        terminal.start()

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
