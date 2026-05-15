"""CLI entry point — defines the alfard command group and registers all subcommands."""

import click
from alfard.cli.cmd_setup import setup
from alfard.cli.cmd_run import run
from alfard.cli.cmd_create import create
from alfard.cli.cmd_connect import connect
from alfard.cli.cmd_edit import edit
from alfard.cli.cmd_list import list_agents
from alfard.cli.cmd_log import log
from alfard.cli.cmd_status import status
from alfard.cli.cmd_skill import skill
from alfard.cli.cmd_cron import cron


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """
    alfard — local AI agents, done right.

    Secure by default. Your data stays on your machine.
    Every action is logged. Irreversible actions need your approval.

    Getting started:
      alfard setup          Configure your LLM provider
      alfard create         Create your first agent
      alfard connect        Connect integrations
      alfard run <agent>    Start chatting

    Docs: https://github.com/bharatknk/alfard
    """
    from pathlib import Path
    config = Path(__file__).parent.parent.parent / "config" / "alfard.yaml"

    if ctx.invoked_subcommand is None:
        if not config.exists():
            from rich.console import Console
            from rich.panel import Panel
            Console().print(Panel(
                "No configuration found.\n\n"
                "Run [bold]alfard setup[/bold] to get started.",
                border_style="grey42"
            ))
        else:
            click.echo(ctx.get_help())


cli.add_command(setup)
cli.add_command(run)
cli.add_command(create)
cli.add_command(connect)
cli.add_command(edit)
cli.add_command(list_agents, name="list")
cli.add_command(log)
cli.add_command(status)
cli.add_command(skill)
cli.add_command(cron)

if __name__ == "__main__":
    cli()
