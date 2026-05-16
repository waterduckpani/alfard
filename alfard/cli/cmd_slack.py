"""CLI command to run an alfard agent as a Slack bot."""

import click
from rich.console import Console
from rich.panel import Panel
from alfard.cli import theme
from alfard.agents.loader import list_agents

console = Console()

@click.command()
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
    from alfard.agents.loader import list_agents

    agents = list_agents()

    if not agents:
        console.print(Panel(
            f"[{theme.ERROR}]No agents found.[/{theme.ERROR}]\n\n"
            "Create one first: [bold]alfard create[/bold]",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)

    # Interactive agent selection if not provided
    if not agent:
        if len(agents) == 1:
            agent = agents[0]
        else:
            from rich.prompt import Prompt
            console.print(f"\n[bold]Which agent should run in Slack?[/bold]")
            for i, a in enumerate(agents, 1):
                console.print(f"  {i}. {a}")
            choice = Prompt.ask("Agent", default="1")
            try:
                agent = agents[int(choice) - 1]
            except (ValueError, IndexError):
                agent = agents[0]

    if agent not in agents:
        console.print(Panel(
            f"[{theme.ERROR}]Agent '{agent}' not found.[/{theme.ERROR}]",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)

    console.print(Panel(
        f"[bold {theme.SUCCESS}]Starting Slack bot[/bold {theme.SUCCESS}]\n\n"
        f"Agent:    {agent}\n"
        f"Mode:     Socket Mode (no public URL needed)\n\n"
        f"[{theme.DIM}]DM @alfard in Slack to start chatting.\n"
        f"Ctrl+C to stop.[/{theme.DIM}]",
        border_style=theme.PANEL_SUCCESS
    ))

    from alfard.interfaces.slack_bot import AlfardSlackBot
    try:
        bot = AlfardSlackBot(agent_name=agent)
        bot.start()
    except RuntimeError as e:
        console.print(Panel(
            f"[{theme.ERROR}]{e}[/{theme.ERROR}]\n\n"
            "Run [bold]alfard connect slack[/bold] first.",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)
