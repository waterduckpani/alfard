"""alfard slack — thin alias for `alfard run`."""

import click
from alfard.cli.help_formatter import AlfardCommand
from alfard.cli.cmd_run import run


@click.command(cls=AlfardCommand, hidden=True)
@click.argument("agent", required=False)
@click.option("--no-mcp", is_flag=True, default=False, hidden=True)
@click.pass_context
def slack(ctx, agent: str | None, no_mcp: bool) -> None:
    """Alias for `alfard run` — starts the agent on all connected channels."""
    ctx.invoke(run, agent=agent, no_mcp=no_mcp)
