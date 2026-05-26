"""alfard doctor — checks the local alfard installation and reports any issues."""

import glob
import shutil
import sys
import yaml
from pathlib import Path

import click

from alfard.cli.help_formatter import AlfardCommand
from alfard.cli.theme import p, c, console
from alfard.paths import ALFARD_HOME


def _row(icon: str, role: str, msg: str) -> None:
    console.print(f"  {c(role, icon)}  {msg}")


def _ok(msg: str) -> None:
    _row("✓", "ok", msg)


def _warn(msg: str) -> None:
    _row("⚠", "warn", msg)


def _err(msg: str) -> None:
    _row("✗", "err", msg)


@click.command(cls=AlfardCommand)
def doctor():
    """Check the alfard installation and report any problems."""
    console.print()
    issues = 0

    # 1. Python version
    major, minor = sys.version_info.major, sys.version_info.minor
    version_str = f"{major}.{minor}.{sys.version_info.micro}"
    if (major, minor) >= (3, 11):
        _ok(f"python {version_str}")
    else:
        _err(f"python {version_str} — alfard requires 3.11 or higher")
        issues += 1

    # 2. alfard on PATH
    alfard_path = shutil.which("alfard")
    if alfard_path:
        _ok(f"alfard on PATH ({alfard_path})")
    else:
        _warn("alfard not on PATH — run: pipx ensurepath")
        issues += 1

    # 3. pipx managed
    pipx_venv = Path.home() / ".local" / "pipx" / "venvs" / "alfard"
    if pipx_venv.exists():
        _ok("pipx managed")
    else:
        _warn("alfard not installed via pipx — reinstall with: pipx install alfard")
        issues += 1

    # 4. Node.js
    node_path = shutil.which("node")
    if node_path:
        _ok("node.js found")
    else:
        _err("node.js not found — required for Notion and GitHub. Install from nodejs.org")
        issues += 1

    # 5. lazy-tool
    from alfard.integrations.lazy_tool import lazy_tool_is_available
    if lazy_tool_is_available():
        _ok("lazy-tool installed")
    else:
        _err("lazy-tool not found — run: alfard setup to reinstall")
        issues += 1

    # 6. gogcli
    if shutil.which("gogcli"):
        _ok("gogcli found")
    else:
        _warn("gogcli not found — needed for Gmail and Google Drive. Run: alfard connect gmail")
        issues += 1

    # 7. ~/.alfard/ exists
    if ALFARD_HOME.exists():
        _ok("~/.alfard/ found")
    else:
        _err("~/.alfard/ missing — run: alfard setup")
        issues += 1

    # 8. alfard.yaml exists and is valid YAML
    config_path = ALFARD_HOME / "config" / "alfard.yaml"
    if config_path.exists():
        try:
            with open(config_path) as f:
                yaml.safe_load(f)
            _ok("config valid")
        except yaml.YAMLError:
            _err("config invalid YAML — run: alfard setup")
            issues += 1
    else:
        _err("config missing — run: alfard setup")
        issues += 1

    # 9. At least one agent
    agents_dir = ALFARD_HOME / "agents"
    agents: list[str] = []
    if agents_dir.exists():
        agents = [d.name for d in agents_dir.iterdir() if d.is_dir()]

    if agents:
        _ok(f"{len(agents)} agent(s) found")
    else:
        _warn("no agents found — run: alfard setup to create one")
        issues += 1

    # 10. Per-agent file checks
    for agent in agents:
        agent_dir = agents_dir / agent
        soul = agent_dir / "soul.md"
        skills = agent_dir / "skills.yaml"
        brain = agent_dir / "brain.db"
        missing = [f for f, path in [("soul.md", soul), ("skills.yaml", skills), ("brain.db", brain)] if not path.exists()]

        if missing:
            _err(f"{agent} — missing files ({', '.join(missing)})")
            issues += 1
        elif skills.exists():
            try:
                with open(skills) as f:
                    data = yaml.safe_load(f)
                if not data:
                    _warn(f"{agent} — skills empty — run: alfard setup")
                    issues += 1
                else:
                    _ok(f"{agent} — ok")
            except yaml.YAMLError:
                _warn(f"{agent} — skills.yaml invalid — run: alfard setup")
                issues += 1
        else:
            _ok(f"{agent} — ok")

    # 11. Stale binaries
    pipx_binary = str(pipx_venv / "bin" / "alfard")
    stale_paths: list[str] = []

    candidates = ["/usr/local/bin/alfard"] + glob.glob(
        "/Library/Frameworks/Python.framework/Versions/*/bin/alfard"
    )
    for path in candidates:
        if Path(path).exists() and path != pipx_binary:
            stale_paths.append(path)

    for path in stale_paths:
        _warn(f"stale binary at {path} — run: alfard uninstall then reinstall with pipx")
        issues += 1

    # Summary
    console.print()
    if issues == 0:
        console.print(f"  {c('fg_dim', 'everything looks good.')}")
    else:
        console.print(f"  {c('warn', str(issues))} {c('fg_dim', f'issue(s) found — see above.')}")
    console.print()
