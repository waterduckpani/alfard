"""Uninstall command — removes all alfard data and the pipx-installed binary."""

import glob
import shutil
import subprocess
from pathlib import Path

import click
from alfard.cli.help_formatter import AlfardCommand


@click.command(cls=AlfardCommand)
def uninstall():
    """Fully remove alfard — binary, data, and credentials."""
    click.echo(
        "\nThis will remove all alfard data including agents, memory, skills,\n"
        "and credentials. This cannot be undone. Type 'yes' to continue: ",
        nl=False,
    )
    answer = input()
    if answer != "yes":
        click.echo("Uninstall cancelled.")
        raise SystemExit(0)

    # a. pipx uninstall
    pipx = shutil.which("pipx")
    if pipx:
        result = subprocess.run([pipx, "uninstall", "alfard"], capture_output=True)
        if result.returncode != 0:
            click.echo("pipx uninstall failed — you may need to run it manually.")
    else:
        click.echo("pipx uninstall failed — you may need to run it manually.")

    # b. delete ~/.alfard/
    alfard_home = Path.home() / ".alfard"
    if alfard_home.exists():
        shutil.rmtree(alfard_home)

    # c. stale binaries
    stale_paths = [
        Path.home() / ".local" / "bin" / "alfard",
        Path("/usr/local/bin/alfard"),
        *[
            Path(p)
            for p in glob.glob(
                "/Library/Frameworks/Python.framework/Versions/*/bin/alfard"
            )
        ],
    ]
    for path in stale_paths:
        if path.exists():
            click.echo(f"removing stale binary: {path}")
            path.unlink()

    # d. done
    click.echo("✓ alfard fully removed.")
    click.echo("To reinstall: pipx install alfard")
