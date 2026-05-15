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

@click.group()
def cli():
    """alfard — secure-by-default local AI agent framework."""
    pass

cli.add_command(setup)
cli.add_command(run)
cli.add_command(create)
cli.add_command(connect)
cli.add_command(edit)
cli.add_command(list_agents, name="list")
cli.add_command(log)
cli.add_command(status)

if __name__ == "__main__":
    cli()
