"""Starts a named agent and enters its interactive ReAct loop."""

import click


@click.command()
@click.argument("agent")
def run(agent):
    # TODO: load agent config and start orchestrator
    pass
