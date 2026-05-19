"""CLI command to run an alfard agent as a Slack bot."""

import click
from alfard.cli.help_formatter import AlfardCommand
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, error_block, alfard_select
from alfard.agents.loader import list_agents


@click.command(cls=AlfardCommand)
@click.argument("agent", required=False)
def slack(agent: str | None):
    """Run an agent as a Slack bot.

    The agent will respond to DMs and @mentions in your Slack
    workspace. Approval gate requests appear as interactive
    messages with Approve/Reject buttons.

    \b
    Examples:
      alfard slack postman
      alfard slack sahil
    """
    agents = list_agents()

    if not agents:
        console.print(error_block(
            agent="alfard slack",
            state="failed",
            headline="no agents found.",
            explanation="create one first: alfard create",
        ))
        raise SystemExit(1)

    if not agent:
        if len(agents) == 1:
            agent = agents[0]
        else:
            agent = alfard_select("which agent should run in slack?", agents, default=agents[0]) or agents[0]

    if agent not in agents:
        console.print(error_block(
            agent="alfard slack",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)

    console.print(f"\n{dot('ok')} [{p.fg_dim}]starting slack bot[/]\n")
    console.print(f"  [{p.fg_faint}]{'agent':<8}[/] [{p.fg_em}]{agent}[/]")
    console.print(f"  [{p.fg_faint}]{'mode':<8}[/] [{p.fg_dim}]socket mode (no public url needed)[/]")
    console.print(f"\n[{p.fg_faint}]dm @alfard in slack to start chatting. ctrl+c to stop.[/]\n")

    from alfard.interfaces.slack_bot import AlfardSlackBot
    try:
        bot = AlfardSlackBot(agent_name=agent)
        bot.start()
    except RuntimeError as e:
        console.print(error_block(
            agent="alfard slack",
            state="failed",
            headline=str(e),
            explanation="run alfard connect slack first.",
        ))
        raise SystemExit(1)
