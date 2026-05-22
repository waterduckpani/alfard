"""Manage alfard agents as systemd services (Linux only)."""

import os
import shutil
import subprocess
import sys

import click
from alfard.cli.help_formatter import AlfardCommand, AlfardGroup
from alfard.agents.loader import list_agents
from alfard.cli.theme import p, console
from alfard.cli.components import error_block, alfard_select


def _assert_linux_systemd() -> None:
    if sys.platform != "linux":
        console.print(
            f"\n[{p.err}]service install is only supported on Linux with systemd.[/]\n"
        )
        raise SystemExit(1)
    if not shutil.which("systemctl"):
        console.print(
            f"\n[{p.err}]service install is only supported on Linux with systemd.[/]\n"
        )
        raise SystemExit(1)


def _service_name(agent_name: str) -> str:
    return f"alfard-{agent_name}"


def _service_path(agent_name: str) -> str:
    return f"/etc/systemd/system/{_service_name(agent_name)}.service"


def _alfard_bin() -> str:
    binary = shutil.which("alfard")
    if binary:
        return binary
    return f"{sys.executable} -m alfard"


@click.group(cls=AlfardGroup)
def service() -> None:
    """Manage alfard agents as system services."""


@service.command(cls=AlfardCommand, name="install")
@click.argument("agent", required=False)
def install(agent: str | None) -> None:
    """Install an agent as a systemd service.

    Writes a service file to /etc/systemd/system/ and enables it.
    Run with sudo.

    \b
    Example:
      sudo alfard service install postman
    """
    _assert_linux_systemd()

    agents = list_agents()
    if not agents:
        console.print(error_block(
            agent="alfard service install",
            state="failed",
            headline="no agents found.",
            explanation="create one first: alfard create",
        ))
        raise SystemExit(1)

    if not agent:
        agent = alfard_select("which agent?", agents)
        if not agent:
            return

    if agent not in agents:
        console.print(error_block(
            agent="alfard service install",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)

    try:
        current_user = os.getlogin()
    except OSError:
        import getpass
        current_user = getpass.getuser()

    cwd = os.getcwd()
    alfard_bin = _alfard_bin()
    svc_name = _service_name(agent)
    svc_path = _service_path(agent)

    unit_content = f"""\
[Unit]
Description=Alfard agent: {agent}
After=network.target

[Service]
Type=simple
User={current_user}
WorkingDirectory={cwd}
ExecStart={alfard_bin} headless {agent}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

    try:
        with open(svc_path, "w", encoding="utf-8") as fh:
            fh.write(unit_content)
    except PermissionError:
        console.print(error_block(
            agent="alfard service install",
            state="failed",
            headline="permission denied writing to /etc/systemd/system/.",
            explanation="run with sudo: sudo alfard service install " + agent,
        ))
        raise SystemExit(1)

    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", svc_name], check=False)

    console.print(f"\n[{p.ok}]service installed.[/]  [{p.fg_em}]{svc_name}[/]\n")
    console.print(
        f"  [{p.fg_faint}]start  [/][{p.fg_dim}]sudo systemctl start {svc_name}[/]"
    )
    console.print(
        f"  [{p.fg_faint}]logs   [/][{p.fg_dim}]journalctl -u {svc_name} -f[/]"
    )
    console.print()


@service.command(cls=AlfardCommand, name="remove")
@click.argument("agent", required=False)
def remove(agent: str | None) -> None:
    """Remove a previously installed systemd service.

    Stops, disables, and deletes the service file.
    Run with sudo.

    \b
    Example:
      sudo alfard service remove postman
    """
    _assert_linux_systemd()

    agents = list_agents()
    if not agents:
        console.print(error_block(
            agent="alfard service remove",
            state="failed",
            headline="no agents found.",
            explanation="",
        ))
        raise SystemExit(1)

    if not agent:
        agent = alfard_select("which agent?", agents)
        if not agent:
            return

    svc_name = _service_name(agent)
    svc_path = _service_path(agent)

    if not os.path.exists(svc_path):
        console.print(
            f"\n[{p.warn}]no service file found for '{agent}'.[/]  "
            f"[{p.fg_faint}]{svc_path}[/]\n"
        )
        raise SystemExit(1)

    subprocess.run(["systemctl", "stop", svc_name], check=False)
    subprocess.run(["systemctl", "disable", svc_name], check=False)

    try:
        os.remove(svc_path)
    except PermissionError:
        console.print(error_block(
            agent="alfard service remove",
            state="failed",
            headline="permission denied removing /etc/systemd/system/ file.",
            explanation="run with sudo: sudo alfard service remove " + agent,
        ))
        raise SystemExit(1)

    subprocess.run(["systemctl", "daemon-reload"], check=False)

    console.print(f"\n[{p.ok}]service removed.[/]  [{p.fg_em}]{svc_name}[/]\n")
