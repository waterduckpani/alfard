"""CLI entry point — defines the alfard command group and registers all subcommands."""

import click
from alfard.cli.help_formatter import AlfardGroup, AlfardCommand
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
from alfard.cli.cmd_disconnect import disconnect
from alfard.cli.cmd_slack import slack
from alfard.cli.cmd_mount import mount


@click.group(cls=AlfardGroup, invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """alfard — local AI agents, done right."""
    from pathlib import Path
    config = Path(__file__).parent.parent.parent / "config" / "alfard.yaml"

    if ctx.invoked_subcommand is not None:
        return

    from alfard.cli.theme import p, console
    from alfard.cli.components import header_block, alfard_select

    if not config.exists():
        console.print()
        console.print(header_block("0.1.0"))
        console.print()
        console.print(f"[{p.fg_dim}]no configuration found. run alfard setup to get started.[/]")
        return

    import questionary

    choices = [
        "run an agent",
        "create a new agent",
        "edit an agent",
        questionary.Separator(),
        "connect an integration",
        "disconnect an integration",
        "manage skills",
        "manage mounts",
        questionary.Separator(),
        "manage cron jobs",
        questionary.Separator(),
        "list agents",
        "view status",
        "view logs",
        questionary.Separator(),
        "settings & setup",
        questionary.Separator(),
        "exit",
    ]

    while True:
        console.clear()
        console.print()
        console.print(header_block("0.1.0"))
        console.print()
        selection = alfard_select("what would you like to do?", choices)

        if not selection or selection == "exit":
            return

        if selection == "run an agent":
            from alfard.agents.loader import list_agents as _list_agents
            agents = _list_agents()
            if not agents:
                console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
            elif len(agents) == 1:
                ctx.invoke(run, agent=agents[0], no_mcp=False)
            else:
                agent_name = alfard_select("which agent?", agents + ["← back"])
                if agent_name and agent_name != "← back":
                    ctx.invoke(run, agent=agent_name, no_mcp=False)
        elif selection == "create a new agent":
            ctx.invoke(create)
        elif selection == "edit an agent":
            from alfard.agents.loader import list_agents as _list_agents2
            agents = _list_agents2()
            if not agents:
                console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
            elif len(agents) == 1:
                agent_name = agents[0]
                file_choice = alfard_select("which file?", ["soul", "brain", "memory", "← back"])
                if file_choice and file_choice != "← back":
                    ctx.invoke(edit, agent=agent_name, file=file_choice)
            else:
                agent_name = alfard_select("which agent?", agents + ["← back"])
                if agent_name and agent_name != "← back":
                    file_choice = alfard_select("which file?", ["soul", "brain", "memory", "← back"])
                    if file_choice and file_choice != "← back":
                        ctx.invoke(edit, agent=agent_name, file=file_choice)
        elif selection == "connect an integration":
            ctx.invoke(connect)
        elif selection == "disconnect an integration":
            ctx.invoke(disconnect)
        elif selection == "manage skills":
            ctx.invoke(skill)
        elif selection == "manage mounts":
            ctx.invoke(mount)
        elif selection == "manage cron jobs":
            ctx.invoke(cron)
        elif selection == "list agents":
            ctx.invoke(list_agents)
        elif selection == "view status":
            ctx.invoke(status)
        elif selection == "view logs":
            ctx.invoke(log)
        elif selection == "settings & setup":
            ctx.invoke(setup)


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
cli.add_command(disconnect)
cli.add_command(slack)
cli.add_command(mount)

if __name__ == "__main__":
    cli()
