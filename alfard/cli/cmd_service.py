"""Manage alfard agents as system services (Linux systemd · macOS launchd · Windows Task Scheduler)."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click
from alfard.agents.loader import AGENTS_DIR, list_agents
from alfard.cli.components import alfard_select, alfard_table, alfard_input, error_block
from alfard.cli.help_formatter import AlfardCommand, AlfardGroup
from alfard.cli.theme import c, console, p


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _assert_supported() -> None:
    if sys.platform == "darwin":
        if not shutil.which("launchctl"):
            console.print(f"\n[{p.err}]launchctl not found — is this macOS?[/]\n")
            raise SystemExit(1)
    elif sys.platform == "linux":
        if not shutil.which("systemctl"):
            console.print(f"\n[{p.err}]systemctl not found — is systemd installed?[/]\n")
            raise SystemExit(1)
    elif sys.platform == "win32":
        if not shutil.which("schtasks"):
            console.print(
                f"\n[{p.err}]schtasks not found — Task Scheduler requires Windows.[/]\n"
            )
            raise SystemExit(1)
    else:
        console.print(
            f"\n[{p.err}]alfard service is only supported on Linux, macOS, and Windows.[/]\n"
        )
        raise SystemExit(1)


def _alfard_bin() -> str:
    return shutil.which("alfard") or f"{sys.executable} -m alfard"


def _is_installed(agent: str) -> bool:
    if sys.platform == "darwin":
        return _mac_plist_path(agent).exists()
    if sys.platform == "win32":
        return _win_is_installed(agent)
    return _unit_path(agent).exists()


def _is_active(agent: str) -> bool:
    if sys.platform == "darwin":
        return _mac_is_running(agent)
    if sys.platform == "win32":
        return _win_is_running(agent)
    rc, _, _ = _ctl("is-active", "--quiet", _service_name(agent))
    return rc == 0


def _pick_installed(cmd: str) -> str | None:
    """Prompt for an agent that has a service config, or return None."""
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
    return alfard_select("which agent?", agents)


# ---------------------------------------------------------------------------
# Linux (systemd) helpers — unchanged
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


def _ctl(*args: str) -> tuple[int, str, str]:
    """Run systemctl --user <args>. Returns (returncode, stdout, stderr)."""
    r = subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout, r.stderr


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


# ---------------------------------------------------------------------------
# macOS (launchd) helpers
# ---------------------------------------------------------------------------

def _mac_label(agent: str) -> str:
    return f"com.alfard.{agent}"


def _mac_plist_dir() -> Path:
    d = Path.home() / "Library" / "LaunchAgents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mac_plist_path(agent: str) -> Path:
    return _mac_plist_dir() / f"{_mac_label(agent)}.plist"


def _mac_plist_content(agent: str) -> str:
    label = _mac_label(agent)
    bin_path = _alfard_bin()
    log_path = AGENTS_DIR / agent / "logs" / "agent.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
        '    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        '    <key>Label</key>\n'
        f'    <string>{label}</string>\n'
        '    <key>ProgramArguments</key>\n'
        '    <array>\n'
        f'        <string>{bin_path}</string>\n'
        '        <string>daemon</string>\n'
        f'        <string>{agent}</string>\n'
        '    </array>\n'
        '    <key>RunAtLoad</key>\n'
        '    <true/>\n'
        '    <key>KeepAlive</key>\n'
        '    <true/>\n'
        '    <key>StandardOutPath</key>\n'
        f'    <string>{log_path}</string>\n'
        '    <key>StandardErrorPath</key>\n'
        f'    <string>{log_path}</string>\n'
        '    <key>EnvironmentVariables</key>\n'
        '    <dict>\n'
        '        <key>PATH</key>\n'
        f'        <string>{path_env}</string>\n'
        '        <key>HOME</key>\n'
        f'        <string>{Path.home()}</string>\n'
        '    </dict>\n'
        '</dict>\n'
        '</plist>\n'
    )


def _lctl(*args: str) -> tuple[int, str, str]:
    """Run launchctl <args>. Returns (returncode, stdout, stderr)."""
    r = subprocess.run(
        ["launchctl", *args],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout, r.stderr


def _mac_is_running(agent: str) -> bool:
    """True when launchd has the service loaded with a live PID."""
    rc, out, _ = _lctl("list", _mac_label(agent))
    if rc != 0:
        return False
    return '"PID"' in out


def _mac_service_props(agent: str) -> dict[str, str]:
    """Parse launchctl list <label> output into a flat dict."""
    rc, out, _ = _lctl("list", _mac_label(agent))
    props: dict[str, str] = {"_loaded": "true" if rc == 0 else "false"}
    if rc != 0:
        return props
    for line in out.splitlines():
        stripped = line.strip().rstrip(";")
        if "=" not in stripped or stripped.startswith(("{", "}")):
            continue
        k, _, v = stripped.partition("=")
        props[k.strip().strip('"')] = v.strip().strip('"')
    return props


def _mac_status_markup(props: dict[str, str]) -> tuple[str, str | None, str | None]:
    """Return (state_markup, pid_or_None, exit_status_or_None)."""
    if props.get("_loaded") != "true":
        return f"[{p.fg_faint}]not loaded[/]", None, None
    pid = props.get("PID")
    if pid:
        return f"[{p.ok}]running[/]", pid, None
    last_exit = props.get("LastExitStatus", "0")
    if last_exit == "0":
        return f"[{p.fg_faint}]stopped[/]", None, None
    return f"[{p.err}]failed[/]", None, last_exit


# ---------------------------------------------------------------------------
# Windows (Task Scheduler) helpers
# ---------------------------------------------------------------------------

def _win_task_name(agent: str) -> str:
    return f"Alfard\\{agent}"


def _schtasks(*args: str) -> tuple[int, str, str]:
    """Run schtasks.exe <args> without shell. Returns (returncode, stdout, stderr)."""
    r = subprocess.run(
        ["schtasks", *args],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout, r.stderr


def _win_is_installed(agent: str) -> bool:
    rc, _, _ = _schtasks("/query", "/tn", _win_task_name(agent))
    return rc == 0


def _win_is_running(agent: str) -> bool:
    rc, out, _ = _schtasks("/query", "/tn", _win_task_name(agent), "/fo", "LIST")
    if rc != 0:
        return False
    for line in out.splitlines():
        if line.strip().startswith("Status:"):
            return "Running" in line
    return False


def _win_status_props(agent: str) -> dict[str, str]:
    """Parse schtasks /query /fo LIST output into a flat dict."""
    rc, out, _ = _schtasks("/query", "/tn", _win_task_name(agent), "/fo", "LIST")
    props: dict[str, str] = {"_found": "true" if rc == 0 else "false"}
    if rc != 0:
        return props
    for line in out.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            props[k.strip()] = v.strip()
    return props


def _win_status_markup(props: dict[str, str]) -> tuple[str, str | None]:
    """Return (state_markup, last_run_or_None)."""
    if props.get("_found") != "true":
        return f"[{p.fg_faint}]not installed[/]", None
    raw_status = props.get("Status", "").lower()
    if "running" in raw_status:
        state = f"[{p.ok}]running[/]"
    elif "disabled" in raw_status:
        state = f"[{p.warn}]disabled[/]"
    elif "ready" in raw_status:
        state = f"[{p.fg_faint}]stopped[/]"
    else:
        state = f"[{p.fg_faint}]{props.get('Status', 'unknown')}[/]"
    last_run = props.get("Last Run Time") or props.get("Letzte Startzeit")
    return state, last_run or None


def _win_sock_alive(agent: str) -> bool:
    """True if either a Unix socket or a TCP port file exists for the agent."""
    base = AGENTS_DIR / agent
    if (base / "agent.sock").exists():
        return True
    return (base / "agent.port").exists()


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

@click.group(cls=AlfardGroup, invoke_without_command=True)
@click.pass_context
def service(ctx: click.Context) -> None:
    """Manage alfard agents as system services.

    Linux:   systemd user units in ~/.config/systemd/user/
    macOS:   launchd agents in ~/Library/LaunchAgents/
    Windows: Task Scheduler tasks under Alfard\\<agent>

    \b
    Examples:
      alfard service install postman
      alfard service list
      alfard service status postman
    """
    if ctx.invoked_subcommand is not None:
        return

    import questionary

    while True:
        console.clear()
        console.print(f"\n[{p.fg_em}]manage services[/]\n")
        svc_pick = alfard_select(
            "what would you like to do?",
            [
                "list service status",
                "install agent as service",
                "start / stop / restart service",
                "remove service",
                questionary.Separator(),
                "view agent log",
                questionary.Separator(),
                "← back",
            ],
        )
        if not svc_pick or svc_pick == "← back":
            return

        if svc_pick == "list service status":
            ctx.invoke(list_services)
            alfard_input("press enter to continue", default="")

        elif svc_pick == "install agent as service":
            _agents = list_agents()
            if not _agents:
                console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                alfard_input("press enter to continue", default="")
            else:
                _pick = alfard_select("which agent?", _agents + ["← back"])
                if _pick and _pick != "← back":
                    ctx.invoke(install, agent=_pick)
                    alfard_input("press enter to continue", default="")

        elif svc_pick == "start / stop / restart service":
            _agents = list_agents()
            if not _agents:
                console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                continue
            _pick = alfard_select("which agent?", _agents + ["← back"])
            if _pick and _pick != "← back":
                _action = alfard_select("action?", ["start", "stop", "restart", "← back"])
                if _action and _action != "← back":
                    ctx.invoke(ctx.command.commands[_action], agent=_pick)
                    alfard_input("press enter to continue", default="")

        elif svc_pick == "remove service":
            _agents = list_agents()
            if not _agents:
                console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                alfard_input("press enter to continue", default="")
            else:
                _pick = alfard_select("which agent?", _agents + ["← back"])
                if _pick and _pick != "← back":
                    ctx.invoke(remove, agent=_pick)
                    alfard_input("press enter to continue", default="")

        elif svc_pick == "view agent log":
            _agents = list_agents()
            if not _agents:
                console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                alfard_input("press enter to continue", default="")
            else:
                _pick = alfard_select("which agent?", _agents + ["← back"])
                if _pick and _pick != "← back":
                    ctx.invoke(logs, agent=_pick)


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="install")
@click.argument("agent", required=False)
def install(agent: str | None) -> None:
    """Install an agent as a system service. No sudo required.

    \b
    Linux:   writes a systemd unit, enables and starts it.
    macOS:   writes a launchd plist, loads it (starts at login).
    Windows: registers a Task Scheduler task (ONLOGON) and starts it.
    \b
    Example:
      alfard service install postman
    """
    _assert_supported()
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

    if sys.platform == "darwin":
        plist = _mac_plist_path(agent)
        label = _mac_label(agent)
        try:
            plist.write_text(_mac_plist_content(agent), encoding="utf-8")
        except OSError as exc:
            console.print(error_block(
                agent="alfard service install",
                state="failed",
                headline="could not write plist file.",
                explanation=str(exc),
            ))
            raise SystemExit(1)
        rc, _, err = _lctl("load", str(plist))
        if rc != 0:
            console.print(error_block(
                agent="alfard service install",
                state="failed",
                headline="launchctl load failed.",
                explanation=err.strip() or f"plist: {plist}",
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]installed and loaded.[/]  [{p.fg_em}]{label}[/]")
        console.print(f"[{p.fg_faint}]plist  → {plist}[/]")
        console.print(f"[{p.fg_faint}]logs   → alfard service logs {agent}[/]")
        console.print(f"\n[{p.ok}]✓ Agent will start automatically on login[/]\n")

    elif sys.platform == "win32":
        task = _win_task_name(agent)
        try:
            user = os.getlogin()
        except OSError:
            user = os.environ.get("USERNAME", "")
        rc, _, err = _schtasks(
            "/create",
            "/tn", task,
            "/tr", f"{_alfard_bin()} daemon {agent}",
            "/sc", "ONLOGON",
            "/ru", user,
            "/rl", "LIMITED",
            "/f",
        )
        if rc != 0:
            console.print(error_block(
                agent="alfard service install",
                state="failed",
                headline="schtasks /create failed.",
                explanation=err.strip() or f"task: {task}",
            ))
            raise SystemExit(1)
        _schtasks("/run", "/tn", task)
        console.print(f"\n[{p.ok}]installed and started.[/]  [{p.fg_em}]{task}[/]")
        console.print(f"[{p.fg_faint}]logs   → alfard service logs {agent}[/]")
        console.print(f"\n[{p.ok}]✓ Agent will start automatically on login[/]\n")

    else:  # linux
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
                headline="could not write unit file.",
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
            f"[{p.fg_dim}]To keep the agent running after logout, run once:[/]\n"
            f"  [{p.fg_faint}]loginctl enable-linger {os.environ.get('USER', '')}[/]\n"
        )


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="remove")
@click.argument("agent", required=False)
def remove(agent: str | None) -> None:
    """Stop and remove the service for an agent.

    \b
    Example:
      alfard service remove postman
    """
    _assert_supported()
    if not agent:
        agent = _pick_installed("remove")
        if not agent:
            return

    if sys.platform == "darwin":
        plist = _mac_plist_path(agent)
        label = _mac_label(agent)
        if not plist.exists():
            console.print(
                f"\n[{p.warn}]no plist found for '{agent}'.[/]\n"
                f"[{p.fg_faint}]expected: {plist}[/]\n"
            )
            raise SystemExit(1)
        _lctl("unload", str(plist))
        plist.unlink(missing_ok=True)
        console.print(f"\n[{p.ok}]removed.[/]  [{p.fg_em}]{label}[/]\n")

    elif sys.platform == "win32":
        task = _win_task_name(agent)
        if not _win_is_installed(agent):
            console.print(
                f"\n[{p.warn}]no task found for '{agent}'.[/]\n"
                f"[{p.fg_faint}]task: {task}[/]\n"
            )
            raise SystemExit(1)
        _schtasks("/end", "/tn", task)
        rc, _, err = _schtasks("/delete", "/tn", task, "/f")
        if rc != 0:
            console.print(error_block(
                agent="alfard service remove",
                state="failed",
                headline="schtasks /delete failed.",
                explanation=err.strip() or f"task: {task}",
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]removed.[/]  [{p.fg_em}]{task}[/]\n")

    else:  # linux
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
# start
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="start")
@click.argument("agent", required=False)
def start(agent: str | None) -> None:
    """Start an installed agent service."""
    _assert_supported()
    if not agent:
        agent = _pick_installed("start")
        if not agent:
            return
    if not _is_installed(agent):
        console.print(
            f"\n[{p.err}]'{agent}' is not installed as a service.[/]\n"
            f"[{p.fg_faint}]Run: alfard service install {agent}[/]\n"
        )
        raise SystemExit(1)

    if sys.platform == "darwin":
        label = _mac_label(agent)
        rc, _, err = _lctl("start", label)
        if rc != 0:
            console.print(error_block(
                agent="alfard service start",
                state="failed",
                headline=f"could not start '{agent}'.",
                explanation=err.strip() or f"label: {label}",
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]started.[/]  [{p.fg_em}]{label}[/]\n")

    elif sys.platform == "win32":
        task = _win_task_name(agent)
        rc, _, err = _schtasks("/run", "/tn", task)
        if rc != 0:
            console.print(error_block(
                agent="alfard service start",
                state="failed",
                headline=f"could not start '{agent}'.",
                explanation=err.strip() or f"task: {task}",
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]started.[/]  [{p.fg_em}]{task}[/]\n")

    else:  # linux
        svc = _service_name(agent)
        rc, _, err = _ctl("start", svc)
        if rc != 0:
            console.print(error_block(
                agent="alfard service start",
                state="failed",
                headline=f"could not start '{agent}'.",
                explanation=err.strip(),
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]started.[/]  [{p.fg_em}]{svc}[/]\n")


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="stop")
@click.argument("agent", required=False)
def stop(agent: str | None) -> None:
    """Stop a running agent service."""
    _assert_supported()
    if not agent:
        agent = _pick_installed("stop")
        if not agent:
            return
    if not _is_installed(agent):
        console.print(f"\n[{p.err}]'{agent}' is not installed as a service.[/]\n")
        raise SystemExit(1)

    if sys.platform == "darwin":
        label = _mac_label(agent)
        rc, _, err = _lctl("stop", label)
        if rc != 0:
            console.print(error_block(
                agent="alfard service stop",
                state="failed",
                headline=f"could not stop '{agent}'.",
                explanation=err.strip() or f"label: {label}",
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]stopped.[/]  [{p.fg_em}]{label}[/]\n")

    elif sys.platform == "win32":
        task = _win_task_name(agent)
        rc, _, err = _schtasks("/end", "/tn", task)
        if rc != 0:
            console.print(error_block(
                agent="alfard service stop",
                state="failed",
                headline=f"could not stop '{agent}'.",
                explanation=err.strip() or f"task: {task}",
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]stopped.[/]  [{p.fg_em}]{task}[/]\n")

    else:  # linux
        svc = _service_name(agent)
        rc, _, err = _ctl("stop", svc)
        if rc != 0:
            console.print(error_block(
                agent="alfard service stop",
                state="failed",
                headline=f"could not stop '{agent}'.",
                explanation=err.strip(),
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]stopped.[/]  [{p.fg_em}]{svc}[/]\n")


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="restart")
@click.argument("agent", required=False)
def restart(agent: str | None) -> None:
    """Restart an agent service."""
    _assert_supported()
    if not agent:
        agent = _pick_installed("restart")
        if not agent:
            return
    if not _is_installed(agent):
        console.print(
            f"\n[{p.err}]'{agent}' is not installed as a service.[/]\n"
            f"[{p.fg_faint}]Run: alfard service install {agent}[/]\n"
        )
        raise SystemExit(1)

    if sys.platform == "darwin":
        label = _mac_label(agent)
        _lctl("stop", label)
        rc, _, err = _lctl("start", label)
        if rc != 0:
            console.print(error_block(
                agent="alfard service restart",
                state="failed",
                headline=f"could not restart '{agent}'.",
                explanation=err.strip() or f"label: {label}",
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]restarted.[/]  [{p.fg_em}]{label}[/]\n")

    elif sys.platform == "win32":
        task = _win_task_name(agent)
        _schtasks("/end", "/tn", task)
        rc, _, err = _schtasks("/run", "/tn", task)
        if rc != 0:
            console.print(error_block(
                agent="alfard service restart",
                state="failed",
                headline=f"could not restart '{agent}'.",
                explanation=err.strip() or f"task: {task}",
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]restarted.[/]  [{p.fg_em}]{task}[/]\n")

    else:  # linux
        svc = _service_name(agent)
        rc, _, err = _ctl("restart", svc)
        if rc != 0:
            console.print(error_block(
                agent="alfard service restart",
                state="failed",
                headline=f"could not restart '{agent}'.",
                explanation=err.strip(),
            ))
            raise SystemExit(1)
        console.print(f"\n[{p.ok}]restarted.[/]  [{p.fg_em}]{svc}[/]\n")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="status")
@click.argument("agent", required=False)
def status(agent: str | None) -> None:
    """Show the service status for an agent in human-readable form."""
    _assert_supported()
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

    console.print()

    if sys.platform == "darwin":
        label = _mac_label(agent)
        props = _mac_service_props(agent)
        state_markup, pid, exit_code = _mac_status_markup(props)
        console.print(f"  [{p.fg_faint}]{'agent':<14}[/] [{p.fg_em}]{agent}[/]")
        console.print(f"  [{p.fg_faint}]{'service':<14}[/] [{p.fg_dim}]{label}[/]")
        console.print(f"  [{p.fg_faint}]{'state':<14}[/] {state_markup}")
        if pid:
            console.print(f"  [{p.fg_faint}]{'pid':<14}[/] [{p.fg_dim}]{pid}[/]")
        if exit_code:
            console.print(f"  [{p.fg_faint}]{'exit status':<14}[/] [{p.err}]{exit_code}[/]")
        console.print(f"  [{p.fg_faint}]{'plist':<14}[/] [{p.fg_dim}]{_mac_plist_path(agent)}[/]")

    elif sys.platform == "win32":
        task = _win_task_name(agent)
        props = _win_status_props(agent)
        state_markup, last_run = _win_status_markup(props)
        console.print(f"  [{p.fg_faint}]{'agent':<14}[/] [{p.fg_em}]{agent}[/]")
        console.print(f"  [{p.fg_faint}]{'task':<14}[/] [{p.fg_dim}]{task}[/]")
        console.print(f"  [{p.fg_faint}]{'state':<14}[/] {state_markup}")
        if last_run:
            console.print(f"  [{p.fg_faint}]{'last run':<14}[/] [{p.fg_dim}]{last_run}[/]")
        next_run = props.get("Next Run Time")
        if next_run:
            console.print(f"  [{p.fg_faint}]{'next run':<14}[/] [{p.fg_dim}]{next_run}[/]")

    else:  # linux
        svc = _service_name(agent)
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

        console.print(f"  [{p.fg_faint}]{'agent':<14}[/] [{p.fg_em}]{agent}[/]")
        console.print(f"  [{p.fg_faint}]{'service':<14}[/] [{p.fg_dim}]{svc}[/]")
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
# logs — platform-agnostic, no changes needed
# ---------------------------------------------------------------------------

@service.command(cls=AlfardCommand, name="logs")
@click.argument("agent", required=False)
@click.option("--lines", "-n", default=50, show_default=True,
              help="Recent lines to show before following")
def logs(agent: str | None, lines: int) -> None:
    """Tail the agent's log file live.

    Reads ~/.alfard/agents/<agent>/logs/agent.log directly.

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
            fh.seek(0, 2)
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
    _assert_supported()
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

        if sys.platform == "win32":
            sock_alive = _win_sock_alive(ag)
        else:
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
