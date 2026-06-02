"""Delete an agent and all its associated data."""

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import click

from alfard.agents.loader import AGENTS_DIR, list_agents
from alfard.cli.components import alfard_input, alfard_select, g
from alfard.cli.help_formatter import AlfardCommand
from alfard.cli.theme import p, console


def _daemon_is_running(agent: str) -> bool:
    """Return True if an agent daemon is currently reachable on its IPC socket."""
    base = AGENTS_DIR / agent
    if sys.platform == "win32":
        port_file = base / "agent.port"
        if not port_file.exists():
            return False
        try:
            port = int(port_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
    else:
        sock_path = base / "agent.sock"
        if not sock_path.exists():
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(str(sock_path))
            return True
        except OSError:
            return False


def _stop_daemon(agent: str) -> bool:
    """Stop the agent daemon. Returns True on success, False if it could not be stopped."""
    base = AGENTS_DIR / agent

    if sys.platform == "win32":
        port_file = base / "agent.port"
        if not port_file.exists():
            return True
        try:
            port = int(port_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return True
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                   capture_output=True, timeout=5)
                    return True
        except Exception:
            pass
        return False

    sock_path = base / "agent.sock"
    if not sock_path.exists():
        return True

    try:
        result = subprocess.run(
            ["lsof", "-t", str(sock_path)],
            capture_output=True, text=True, timeout=5,
        )
        pids = [int(tok) for tok in result.stdout.split() if tok.isdigit()]
    except Exception:
        return False

    if not pids:
        return True

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            os.kill(pids[0], 0)
            time.sleep(0.2)
        except ProcessLookupError:
            return True

    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    return True


def _remove_agent_from_config(agent: str) -> None:
    """Remove references to the agent from alfard.yaml and integrations.yaml if present."""
    from alfard.paths import ALFARD_HOME
    import yaml

    for cfg_name in ("alfard.yaml", "integrations.yaml"):
        cfg_path = ALFARD_HOME / "config" / cfg_name
        if not cfg_path.exists():
            continue
        try:
            with open(cfg_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            continue

        modified = False

        if cfg_name == "integrations.yaml":
            servers = data.get("servers", [])
            if isinstance(servers, list):
                filtered = [s for s in servers if s.get("agent") != agent]
                if len(filtered) != len(servers):
                    data["servers"] = filtered
                    modified = True

        if cfg_name == "alfard.yaml":
            if data.get("default_agent") == agent:
                del data["default_agent"]
                modified = True

        if modified:
            try:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
            except Exception:
                pass


def _print_warning_panel(agent_name: str) -> None:
    width = 51
    tl, tr = g["tl"], g["tr"]
    bl, br = g["bl"], g["br"]
    h, v = g["h"], g["v"]

    def row(text: str = "") -> str:
        visible = len(text.replace("[/]", "").replace(f"[{p.err}]", "").replace(f"[{p.fg_em}]", "").replace(f"[{p.fg_dim}]", ""))
        # strip all markup for width calculation
        import re
        plain = re.sub(r"\[[^\]]*\]", "", text)
        pad = width - 2 - len(plain)
        return f"  {v}  {text}{' ' * max(0, pad)}{v}"

    title = f"{h} delete agent {h * (width - 16)}"
    console.print(f"  [{p.fg_dim}]{tl}{title}{tr}[/]")
    console.print(row(f"[{p.err}]⚠  This will permanently delete:[/]"))
    console.print(row())
    console.print(row(f"[{p.fg_em}]   {agent_name}[/]"))
    console.print(row())
    console.print(row(f"[{p.fg_dim}]• soul.md — identity[/]"))
    console.print(row(f"[{p.fg_dim}]• brain.db — all memory[/]"))
    console.print(row(f"[{p.fg_dim}]• skills.yaml — skill config[/]"))
    console.print(row(f"[{p.fg_dim}]• crons.yaml — scheduled jobs[/]"))
    console.print(row(f"[{p.fg_dim}]• all session history[/]"))
    console.print(row(f"[{p.fg_dim}]• all logs[/]"))
    console.print(row())
    console.print(row(f"[{p.err}]This cannot be undone.[/]"))
    console.print(f"  [{p.fg_dim}]{bl}{h * (width - 2)}{br}[/]")


@click.command(cls=AlfardCommand)
@click.argument("agent", required=False)
def delete(agent: str | None) -> None:
    """Delete an agent and all its data permanently.

    Stops the agent's daemon if running, then removes the entire agent
    directory. Requires typing the agent name to confirm.

    \b
    Example:
      alfard agent delete postman
    """
    agents = list_agents()
    if not agents:
        console.print(f"\n[{p.fg_dim}]no agents found.[/]\n")
        return

    if not agent:
        agent = alfard_select("which agent to delete?", agents + ["← back"])
        if not agent or agent == "← back":
            return

    if agent not in agents:
        console.print(f"\n[{p.err}]agent '{agent}' not found.[/]\n")
        raise SystemExit(1)

    # Validate path — no traversal possible
    agent_dir = (AGENTS_DIR / agent).resolve()
    agents_dir_resolved = AGENTS_DIR.resolve()
    try:
        agent_dir.relative_to(agents_dir_resolved)
    except ValueError:
        console.print(f"\n[{p.err}]invalid agent path — aborting.[/]\n")
        raise SystemExit(1)

    console.print()
    _print_warning_panel(agent)
    console.print()
    console.print(f"  [{p.fg_dim}]Type the agent name to confirm deletion:[/]")
    console.print()

    typed = alfard_input(f"  agent name", default="").strip()

    if typed != agent:
        console.print()
        console.print(f"  [{p.err}]name did not match — deletion cancelled[/]")
        console.print()
        return

    # Stop daemon if running
    console.print()
    if _daemon_is_running(agent):
        console.print(f"  [{p.fg_dim}]stopping daemon...[/]")
        stopped = _stop_daemon(agent)
        if not stopped:
            console.print(
                f"  [{p.warn}]⚠ could not stop running daemon — "
                f"files deleted but process may still be running.[/]"
            )
            console.print(
                f"  [{p.fg_faint}]Run: alfard service stop {agent}[/]"
            )

    # Delete agent directory
    try:
        shutil.rmtree(agent_dir)
    except OSError as exc:
        console.print(f"  [{p.err}]failed to delete agent directory: {exc}[/]")
        raise SystemExit(1) from exc

    # Clean up global config references
    _remove_agent_from_config(agent)

    console.print(f"  [{p.ok}]✓ agent {agent} deleted[/]")
    console.print()
