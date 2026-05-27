"""Manage alfard agents as systemd user services (Linux only)."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click
from alfard.agents.loader import AGENTS_DIR, list_agents
from alfard.cli.components import alfard_select, alfard_table, error_block
from alfard.cli.help_formatter import AlfardCommand, AlfardGroup
from alfard.cli.theme import c, console, p


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _assert_linux() -> None:
    if sys.platform != "linux":
        console.print(f"\n[{p.err}]alfard service requires Linux with systemd.[/]\n")
        raise SystemExit(1)
    if not shutil.which("systemctl"):
        console.print(f"\n[{p.err}]systemctl not found — is systemd installed?[/]\n")
        raise SystemExit(1)


def _service_name(agent: str) -> str:
    return f"alfard-{agent}"


def _unit_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".config"
    d = base / "systemd" / "user"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _unit_path(agent: str) -> Path:
    return _unit_dir() / f"{_service_name(agent)}.service"


def _alfard_bin() -> str:
    return shutil.which("alfard") or f"{sys.executable} -m alfard"


def _ctl(*args: str) -> tuple[int, str, str]:
    """Run systemctl --user <args>. Returns (returncode, stdout, stderr)."""
    r = subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout, r.stderr


def _is_installed(agent: str) -> bool:
    return _unit_path(agent).exists()


def _is_active(agent: str) -> bool:
    rc, _, _ = _ctl("is-active", "--quiet", _service_name(agent))
    return rc == 0


def _service_props(agent: str) -> dict[str, str]:
    """Return selected properties from systemctl show as a dict."""
    rc, out, _ = _ctl(
        "show", _service_name(agent),
        "--property=ActiveState,SubState,MainPID,"
        "ExecMainStartTimestamp,Result",
    )
    props: dict[str, str] = {}
    if rc != 0:
        return props
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props


def _pick_installed(cmd: str) -> str | None:
    """Prompt for an agent that has a unit file, or return None."""
    agents = list_agents()
    installed = [a for a in agents if _is_installed(a)]
    if not installed:
        console.print(
            f"\n[{p.warn}]no installed services found.[/]\n"
            f"[{p.fg_faint}]Run: alfard service install <agent>[/]\n"
        )
        return None
    if len(installed) == 1:
        return installed[0]
    return alfard_select(f"which agent? (alfard service {cmd})", installed)


def _pick_any(cmd: str) -> str | None:
    """Prompt for any known agent, or return None."""
    agents = list_agents()
    if not agents:
        console.print(error_block(
            agent=f"alfard service {cmd}",
            state="failed",
            headline="no agents found.",
            explanation="create one first: alfard create",
        ))
        return None
    if len(agents) == 1:
        return agents[0]
    return alfard_select(f"which agent?", agents)


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

@click.group(cls=AlfardGroup, invoke_without_command=True)
@click.pass_context
def service(ctx: click.Context) -> None:
    """Manage alfard agents as systemd user services (Linux only).

    \b
    Examples:
      alfard service install postman
      alfard service list
      alfard service status postman
    """
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="install")
@click.argument("agent", required=False)
def install(agent: str | None) -> None:
    """Install an agent as a systemd user service.

    Writes a unit file to ~/.config/systemd/user/ and enables it.
    No sudo required.

    \b
    Example:
      alfard service install postman
    """
    _assert_linux()
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
        agent = _pick_any("install")
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

    unit = _unit_path(agent)
    svc = _service_name(agent)

    unit_content = (
        "[Unit]\n"
        f"Description=alfard agent: {agent}\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={_alfard_bin()} daemon {agent}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        f"Environment=HOME={Path.home()}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )

    try:
        unit.write_text(unit_content, encoding="utf-8")
    except OSError as exc:
        console.print(error_block(
            agent="alfard service install",
            state="failed",
            headline=f"could not write unit file.",
            explanation=str(exc),
        ))
        raise SystemExit(1)

    _ctl("daemon-reload")
    rc, _, err = _ctl("enable", "--now", svc)
    if rc != 0:
        console.print(error_block(
            agent="alfard service install",
            state="failed",
            headline="systemctl enable failed.",
            explanation=err.strip() or f"unit: {unit}",
        ))
        raise SystemExit(1)

    console.print(f"\n[{p.ok}]installed and started.[/]  [{p.fg_em}]{svc}[/]")
    console.print(f"[{p.fg_faint}]unit   → {unit}[/]")
    console.print(f"[{p.fg_faint}]logs   → alfard service logs {agent}[/]\n")
    console.print(
        f"[{p.fg_dim}]To persist across reboots without login:[/]\n"
        f"  [{p.fg_faint}]loginctl enable-linger {os.environ.get('USER', '')}[/]\n"
    )


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="remove")
@click.argument("agent", required=False)
def remove(agent: str | None) -> None:
    """Stop, disable, and remove the systemd unit for an agent.

    \b
    Example:
      alfard service remove postman
    """
    _assert_linux()
    if not agent:
        agent = _pick_installed("remove")
        if not agent:
            return

    unit = _unit_path(agent)
    svc = _service_name(agent)

    if not unit.exists():
        console.print(
            f"\n[{p.warn}]no unit file found for '{agent}'.[/]\n"
            f"[{p.fg_faint}]expected: {unit}[/]\n"
        )
        raise SystemExit(1)

    _ctl("stop", svc)
    _ctl("disable", svc)
    unit.unlink(missing_ok=True)
    _ctl("daemon-reload")

    console.print(f"\n[{p.ok}]removed.[/]  [{p.fg_em}]{svc}[/]\n")


# ---------------------------------------------------------------------------
# start / stop / restart
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="start")
@click.argument("agent", required=False)
def start(agent: str | None) -> None:
    """Start an installed agent service."""
    _assert_linux()
    if not agent:
        agent = _pick_installed("start")
        if not agent:
            return
    if not _is_installed(agent):
        console.print(
            f"\n[{p.err}]'{agent}' has no unit file.[/]\n"
            f"[{p.fg_faint}]Run: alfard service install {agent}[/]\n"
        )
        raise SystemExit(1)
    rc, _, err = _ctl("start", _service_name(agent))
    if rc != 0:
        console.print(error_block(
            agent="alfard service start",
            state="failed",
            headline=f"could not start '{agent}'.",
            explanation=err.strip(),
        ))
        raise SystemExit(1)
    console.print(f"\n[{p.ok}]started.[/]  [{p.fg_em}]{_service_name(agent)}[/]\n")


@service.command(cls=AlfardCommand, name="stop")
@click.argument("agent", required=False)
def stop(agent: str | None) -> None:
    """Stop a running agent service."""
    _assert_linux()
    if not agent:
        agent = _pick_installed("stop")
        if not agent:
            return
    if not _is_installed(agent):
        console.print(
            f"\n[{p.err}]'{agent}' has no unit file.[/]\n"
        )
        raise SystemExit(1)
    rc, _, err = _ctl("stop", _service_name(agent))
    if rc != 0:
        console.print(error_block(
            agent="alfard service stop",
            state="failed",
            headline=f"could not stop '{agent}'.",
            explanation=err.strip(),
        ))
        raise SystemExit(1)
    console.print(f"\n[{p.ok}]stopped.[/]  [{p.fg_em}]{_service_name(agent)}[/]\n")


@service.command(cls=AlfardCommand, name="restart")
@click.argument("agent", required=False)
def restart(agent: str | None) -> None:
    """Restart an agent service."""
    _assert_linux()
    if not agent:
        agent = _pick_installed("restart")
        if not agent:
            return
    if not _is_installed(agent):
        console.print(
            f"\n[{p.err}]'{agent}' has no unit file.[/]\n"
            f"[{p.fg_faint}]Run: alfard service install {agent}[/]\n"
        )
        raise SystemExit(1)
    rc, _, err = _ctl("restart", _service_name(agent))
    if rc != 0:
        console.print(error_block(
            agent="alfard service restart",
            state="failed",
            headline=f"could not restart '{agent}'.",
            explanation=err.strip(),
        ))
        raise SystemExit(1)
    console.print(f"\n[{p.ok}]restarted.[/]  [{p.fg_em}]{_service_name(agent)}[/]\n")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="status")
@click.argument("agent", required=False)
def status(agent: str | None) -> None:
    """Show the service status for an agent in human-readable form."""
    _assert_linux()
    if not agent:
        agent = _pick_any("status")
        if not agent:
            return
    if not _is_installed(agent):
        console.print(
            f"\n[{p.warn}]'{agent}' is not installed as a service.[/]\n"
            f"[{p.fg_faint}]Run: alfard service install {agent}[/]\n"
        )
        return

    props = _service_props(agent)
    active = props.get("ActiveState", "unknown")
    sub = props.get("SubState", "")
    pid = props.get("MainPID", "0")
    started = props.get("ExecMainStartTimestamp", "")
    result = props.get("Result", "")

    if active == "active":
        state_markup = f"[{p.ok}]running[/]"
    elif active == "failed":
        state_markup = f"[{p.err}]failed[/]"
    elif active in ("activating", "deactivating"):
        state_markup = f"[{p.warn}]{active}…[/]"
    elif active == "inactive":
        state_markup = f"[{p.fg_faint}]stopped[/]"
    else:
        state_markup = f"[{p.fg_faint}]{active}[/]"

    console.print()
    console.print(f"  [{p.fg_faint}]{'agent':<14}[/] [{p.fg_em}]{agent}[/]")
    console.print(f"  [{p.fg_faint}]{'service':<14}[/] [{p.fg_dim}]{_service_name(agent)}[/]")
    console.print(f"  [{p.fg_faint}]{'state':<14}[/] {state_markup}")
    if sub and sub not in (active, ""):
        console.print(f"  [{p.fg_faint}]{'detail':<14}[/] [{p.fg_dim}]{sub}[/]")
    if pid and pid != "0":
        console.print(f"  [{p.fg_faint}]{'pid':<14}[/] [{p.fg_dim}]{pid}[/]")
    if started:
        console.print(f"  [{p.fg_faint}]{'started':<14}[/] [{p.fg_dim}]{started}[/]")
    if result and result not in ("success", ""):
        console.print(f"  [{p.fg_faint}]{'exit reason':<14}[/] [{p.err}]{result}[/]")
    console.print()


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="logs")
@click.argument("agent", required=False)
@click.option("--lines", "-n", default=50, show_default=True,
              help="Recent lines to show before following")
def logs(agent: str | None, lines: int) -> None:
    """Tail the agent's log file live.

    Does not require systemd — reads ~/.alfard/agents/<agent>/logs/agent.log.

    \b
    Examples:
      alfard service logs postman
      alfard service logs postman -n 100
    """
    if not agent:
        agent = _pick_any("logs")
        if not agent:
            return

    log_path = AGENTS_DIR / agent / "logs" / "agent.log"
    if not log_path.exists():
        console.print(
            f"\n[{p.warn}]no log file found for '{agent}'.[/]\n"
            f"[{p.fg_faint}]path: {log_path}[/]\n"
            f"[{p.fg_faint}]start the service first: alfard service start {agent}[/]\n"
        )
        return

    console.print(f"[{p.fg_faint}]{log_path}  ·  ctrl+c to stop[/]\n")

    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
            for line in all_lines[-lines:]:
                console.print(line.rstrip(), highlight=False)
            fh.seek(0, 2)  # seek to end before following
            try:
                while True:
                    line = fh.readline()
                    if line:
                        console.print(line.rstrip(), highlight=False)
                    else:
                        time.sleep(0.2)
            except KeyboardInterrupt:
                pass
    except OSError as exc:
        console.print(f"\n[{p.err}]could not read log: {exc}[/]\n")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="list")
def list_services() -> None:
    """List all agents with their service install and run state."""
    _assert_linux()
    agents = list_agents()
    if not agents:
        console.print(
            f"[{p.fg_dim}]no agents found.[/]\n"
            f"[{p.fg_faint}]create one: alfard create[/]"
        )
        return

    rows = []
    for ag in agents:
        installed = _is_installed(ag)
        if installed:
            running = _is_active(ag)
            inst_str = c("ok", "yes")
            run_str = c("ok", "yes") if running else c("fg_faint", "no")
        else:
            inst_str = c("fg_faint", "no")
            run_str = c("fg_faint", "—")

        sock_alive = (AGENTS_DIR / ag / "agent.sock").exists()
        sock_str = c("ok", "yes") if sock_alive else c("fg_faint", "no")

        rows.append({
            "agent":     ag,
            "installed": inst_str,
            "running":   run_str,
            "socket":    sock_str,
        })

    console.print(alfard_table(
        [
            {"header": "agent",     "key": "agent"},
            {"header": "installed", "key": "installed"},
            {"header": "running",   "key": "running"},
            {"header": "socket",    "key": "socket"},
        ],
        rows,
    ))
