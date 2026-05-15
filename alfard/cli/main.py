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

@click.group()
def cli():
    """
    alfard — local AI agents, done right.

    Secure by default. Your data stays on your machine.
    Every action is logged. Irreversible actions need your approval.

    Getting started:
      alfard setup          Configure your LLM provider
      alfard create         Create your first agent
      alfard connect        Connect integrations
      alfard run <agent>    Start chatting

    Docs: https://github.com/yourusername/alfard
    """
    pass

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
