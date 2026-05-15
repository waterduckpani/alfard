"""First-run setup command — configures alfard interactively."""

import click
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from setup_alfard import run_setup


@click.command()
def setup():
    """Set up alfard — configure provider, create your first agent."""
    run_setup()
