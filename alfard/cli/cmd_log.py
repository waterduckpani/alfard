"""Displays the audit log for a named agent."""

import click


@click.command()
@click.argument("agent")
def log(agent):
    # TODO: read and pretty-print the agent's append-only audit log
    pass
