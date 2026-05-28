"""Uninstall command — removes all alfard data and the pipx-installed binary."""

import glob
import shutil
import subprocess
from pathlib import Path

import click
from alfard.cli.help_formatter import AlfardCommand
from alfard.cli.theme import p, console
from alfard.cli.components import dot, alfard_confirm


@click.command(cls=AlfardCommand)
def uninstall():
    """Fully remove alfard — binary, data, and credentials."""
    console.print(
        f"\n{dot('warn')} [{p.warn}]uninstall alfard[/]\n"
        f"[{p.fg_faint}]this will remove all data including agents, memory, skills, and credentials.[/]"
    )
    if not alfard_confirm("remove all alfard data and the binary?", default=False):
        console.print(f"[{p.fg_dim}]cancelled.[/]")
        return

    # a. pipx uninstall
    pipx = shutil.which("pipx")
    if pipx:
        result = subprocess.run([pipx, "uninstall", "alfard"], capture_output=True)
        if result.returncode != 0:
            console.print(
                f"{dot('warn')} [{p.warn}]pipx uninstall failed — you may need to run it manually.[/]"
            )
    else:
        console.print(
            f"{dot('warn')} [{p.warn}]pipx uninstall failed — you may need to run it manually.[/]"
        )

    # b. delete ~/.alfard/
    alfard_home = Path.home() / ".alfard"
    if alfard_home.exists():
        shutil.rmtree(alfard_home)

    # c. stale binaries
    import sys as _sys
    if _sys.platform == "win32":
        import os as _os
        stale_paths = [
            Path(_os.environ.get("LOCALAPPDATA", "")) / "Programs" / "alfard" / "alfard.exe",
            Path(_os.environ.get("APPDATA", "")) / "Python" / "Scripts" / "alfard.exe",
        ]
    else:
        stale_paths = [
            Path.home() / ".local" / "bin" / "alfard",
            Path("/usr/local/bin/alfard"),
            *[
                Path(path_str)
                for path_str in glob.glob(
                    "/Library/Frameworks/Python.framework/Versions/*/bin/alfard"
                )
            ],
        ]
    for path in stale_paths:
        if path.exists():
            console.print(f"  [{p.fg_faint}]removing stale binary: {path}[/]")
            path.unlink()

    # d. done
    console.print(f"\n{dot('ok')} [{p.fg_dim}]alfard fully removed.[/]")
    console.print(f"[{p.fg_faint}]to reinstall: pipx install alfard[/]")
