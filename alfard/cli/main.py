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
from alfard.cli.cmd_memory import memory


@click.group(cls=AlfardGroup, invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """alfard — local AI agents, done right."""
    from alfard.paths import ALFARD_HOME, load_env
    config = ALFARD_HOME / "config" / "alfard.yaml"

    if not ALFARD_HOME.exists() and ctx.invoked_subcommand not in (None, "setup"):
        from alfard.cli.theme import console
        console.print("Run alfard setup to get started.")
        raise SystemExit(0)

    if ctx.invoked_subcommand is not None:
        return

    from alfard.cli.theme import p, console
    from alfard.cli.components import header_block, alfard_select, alfard_input, alfard_confirm

    if not config.exists():
        console.print()
        console.print(header_block("0.1.0"))
        console.print()
        console.print(f"[{p.fg_dim}]Run alfard setup to get started.[/]")
        return

    import questionary

    choices = [
        "run an agent",
        "run slack bot",
        questionary.Separator(),
        "create a new agent",
        "edit an agent",
        "list agents",
        questionary.Separator(),
        "connect an integration",
        "disconnect an integration",
        questionary.Separator(),
        "manage skills",
        "manage mounts",
        "manage cron jobs",
        questionary.Separator(),
        "manage memory",
        questionary.Separator(),
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
            import questionary as _q
            from pathlib import Path as _Path
            from alfard.integrations.catalogue import CATALOGUE
            from alfard.cli.cmd_connect import _load_integrations
            from alfard.agents.loader import list_agents as _list_agents_web, AGENTS_DIR as _AGENTS_DIR
            from alfard.web.config import WebConfig as _WebConfig
            load_env()
            connected = {s["name"] for s in _load_integrations().get("servers", [])}
            if (_Path.home() / ".config" / "gws" / "credentials.enc").exists():
                connected.update({"gmail", "gdrive"})
            web_configured = any(
                _WebConfig(_AGENTS_DIR / a).enabled for a in _list_agents_web()
            )
            int_choices = [
                _q.Choice(
                    title=f"{info['display_name']}{' (connected)' if name in connected else ''}",
                    value=name,
                    description=info["description"],
                )
                for name, info in CATALOGUE.items()
            ] + [
                _q.Choice(
                    title=f"web access{' (configured)' if web_configured else ''}",
                    value="web-access",
                    description="Configure web search and page fetching for an agent",
                ),
                _q.Choice(title="← back", value="← back"),
            ]
            pick = alfard_select("which integration?", int_choices)
            if pick and pick != "← back":
                ctx.invoke(connect, integration=pick)
                alfard_input("press enter to continue", default="")
        elif selection == "disconnect an integration":
            ctx.invoke(disconnect)
            alfard_input("press enter to continue", default="")
        elif selection == "manage skills":
            ctx.invoke(skill)
        elif selection == "manage mounts":
            ctx.invoke(mount)
        elif selection == "run slack bot":
            from alfard.agents.loader import list_agents as _list_agents_slack
            import os as _os_slack
            load_env()
            if not _os_slack.environ.get("SLACK_APP_TOKEN"):
                console.print(f"\n[{p.fg_dim}]slack bot not configured.[/]")
                console.print(f"[{p.fg_faint}]run: alfard connect slack-bot[/]")
                alfard_input("press enter to continue", default="")
            else:
                agents = _list_agents_slack()
                if not agents:
                    console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                    alfard_input("press enter to continue", default="")
                elif len(agents) == 1:
                    ctx.invoke(slack, agent=agents[0])
                else:
                    agent_name = alfard_select("which agent?", agents + ["← back"])
                    if agent_name and agent_name != "← back":
                        ctx.invoke(slack, agent=agent_name)
        elif selection == "manage cron jobs":
            ctx.invoke(cron)
        elif selection == "manage memory":
            ctx.invoke(memory)
        elif selection == "list agents":
            ctx.invoke(list_agents)
            alfard_input("press enter to continue", default="")
        elif selection == "view status":
            ctx.invoke(status)
            alfard_input("press enter to continue", default="")
        elif selection == "view logs":
            ctx.invoke(log)
            alfard_input("press enter to continue", default="")
        elif selection == "settings & setup":
            from alfard.paths import ALFARD_HOME
            import shutil
            sub = alfard_select(
                "settings & setup",
                [
                    "re-run setup",
                    "reset alfard",
                    questionary.Separator(),
                    "← back",
                ],
            )
            if sub == "re-run setup":
                ctx.invoke(setup)
            elif sub == "reset alfard":
                console.print()
                console.print(
                    f"  [{p.err}]warning:[/] this will permanently delete all of your alfard data."
                )
                console.print(
                    f"  [{p.fg_dim}]this includes your config, agents, integrations, env file, and logs.[/]"
                )
                console.print()
                first = alfard_confirm("are you sure you want to delete everything?", default=False)
                if first:
                    console.print()
                    console.print(
                        f"  [{p.err}]final warning:[/] there is no undo. [{p.fg_em}]{ALFARD_HOME}[/] will be deleted."
                    )
                    console.print()
                    second = alfard_confirm("delete all alfard data permanently?", default=False)
                    if second:
                        shutil.rmtree(ALFARD_HOME, ignore_errors=True)
                        console.print()
                        console.print(f"  [{p.ok}]done.[/] alfard has been reset.")
                        console.print(
                            f"  [{p.fg_dim}]run [/][{p.fg_em}]alfard setup[/][{p.fg_dim}] to start fresh.[/]"
                        )
                        console.print()
                        return


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
cli.add_command(memory)

if __name__ == "__main__":
    cli()
