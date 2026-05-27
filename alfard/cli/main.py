"""CLI entry point — defines the alfard command group and registers all subcommands."""

from importlib.metadata import version as pkg_version
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
from alfard.cli.cmd_headless import headless, _has_headless_channels
from alfard.cli.cmd_service import service
from alfard.cli.cmd_channel import channel, connected_channels
from alfard.cli.cmd_uninstall import uninstall
from alfard.cli.cmd_doctor import doctor
from alfard.cli.cmd_daemon import daemon


@click.group(cls=AlfardGroup, invoke_without_command=True)
@click.version_option(version=pkg_version("alfard"), prog_name="alfard")
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
        console.print(header_block(pkg_version("alfard")))
        console.print()
        console.print(f"[{p.fg_dim}]Run alfard setup to get started.[/]")
        return

    import questionary

    choices = [
        "run an agent",
        "run headless",
        questionary.Separator(),
        "create a new agent",
        "edit an agent",
        "list agents",
        questionary.Separator(),
        "connect a channel",
        "disconnect a channel",
        questionary.Separator(),
        "connect an integration",
        "disconnect an integration",
        questionary.Separator(),
        "manage skills",
        "manage mounts",
        "manage cron jobs",
        "manage services",
        questionary.Separator(),
        "manage memory",
        questionary.Separator(),
        "view status",
        "view logs",
        questionary.Separator(),
        "run doctor",
        questionary.Separator(),
        "settings & setup",
        questionary.Separator(),
        "exit",
    ]

    while True:
        console.clear()
        console.print()
        console.print(header_block(pkg_version("alfard")))
        console.print()
        selection = alfard_select("what would you like to do?", choices)

        if not selection or selection == "exit":
            return

        if selection == "run an agent":
            from alfard.agents.loader import list_agents as _list_agents
            agents = _list_agents()
            if not agents:
                console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                alfard_input("press enter to continue", default="")
            elif len(agents) == 1:
                ctx.invoke(run, agent=agents[0], no_mcp=False)
            else:
                agent_name = alfard_select("which agent?", agents + ["← back"])
                if agent_name and agent_name != "← back":
                    ctx.invoke(run, agent=agent_name, no_mcp=False)
        elif selection == "run headless":
            load_env()
            from alfard.agents.loader import list_agents as _list_agents_hl
            agents = _list_agents_hl()
            if not agents:
                console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                alfard_input("press enter to continue", default="")
            elif not _has_headless_channels():
                console.print(f"\n[{p.fg_dim}]no channels configured yet.[/]")
                console.print(f"[{p.fg_faint}]connect one first: alfard channel connect[/]")
                alfard_input("press enter to continue", default="")
            elif len(agents) == 1:
                ctx.invoke(headless, agent=agents[0], no_mcp=False)
            else:
                agent_name = alfard_select("which agent?", agents + ["← back"])
                if agent_name and agent_name != "← back":
                    ctx.invoke(headless, agent=agent_name, no_mcp=False)
        elif selection == "create a new agent":
            ctx.invoke(create)
            alfard_input("press enter to continue", default="")
        elif selection == "edit an agent":
            from alfard.agents.loader import list_agents as _list_agents2
            agents = _list_agents2()
            if not agents:
                console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                alfard_input("press enter to continue", default="")
            elif len(agents) == 1:
                agent_name = agents[0]
                file_choice = alfard_select("which file?", ["soul", "brain", "memory", "← back"])
                if file_choice and file_choice != "← back":
                    ctx.invoke(edit, agent=agent_name, file=file_choice)
                    alfard_input("press enter to continue", default="")
            else:
                agent_name = alfard_select("which agent?", agents + ["← back"])
                if agent_name and agent_name != "← back":
                    file_choice = alfard_select("which file?", ["soul", "brain", "memory", "← back"])
                    if file_choice and file_choice != "← back":
                        ctx.invoke(edit, agent=agent_name, file=file_choice)
                        alfard_input("press enter to continue", default="")
        elif selection == "connect a channel":
            ctx.invoke(channel.commands["connect"])
            alfard_input("press enter to continue", default="")
        elif selection == "disconnect a channel":
            load_env()
            if not connected_channels():
                console.print(f"\n[{p.fg_dim}]no channels connected.[/]")
                console.print(f"[{p.fg_faint}]connect one first: alfard channel connect[/]")
                alfard_input("press enter to continue", default="")
            else:
                ctx.invoke(channel.commands["disconnect"])
                alfard_input("press enter to continue", default="")
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
        elif selection == "manage cron jobs":
            ctx.invoke(cron)
        elif selection == "manage services":
            from alfard.agents.loader import list_agents as _svc_list_agents
            while True:
                svc_pick = alfard_select(
                    "manage services",
                    [
                        "list service status",
                        "install agent as service",
                        "start / stop / restart service",
                        "remove service",
                        questionary.Separator(),
                        "view agent logs",
                        questionary.Separator(),
                        "← back",
                    ],
                )
                if not svc_pick or svc_pick == "← back":
                    break

                if svc_pick == "list service status":
                    ctx.invoke(service.commands["list"])
                    alfard_input("press enter to continue", default="")

                elif svc_pick == "install agent as service":
                    _agents = _svc_list_agents()
                    if not _agents:
                        console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                        alfard_input("press enter to continue", default="")
                    else:
                        _pick = alfard_select("which agent?", _agents + ["← back"])
                        if _pick and _pick != "← back":
                            ctx.invoke(service.commands["install"], agent=_pick)
                            alfard_input("press enter to continue", default="")

                elif svc_pick == "start / stop / restart service":
                    _agents = _svc_list_agents()
                    if not _agents:
                        console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                        alfard_input("press enter to continue", default="")
                    else:
                        _pick = alfard_select("which agent?", _agents + ["← back"])
                        if _pick and _pick != "← back":
                            _action = alfard_select("action?", ["start", "stop", "restart", "← back"])
                            if _action and _action != "← back":
                                ctx.invoke(service.commands[_action], agent=_pick)
                                alfard_input("press enter to continue", default="")

                elif svc_pick == "remove service":
                    _agents = _svc_list_agents()
                    if not _agents:
                        console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                        alfard_input("press enter to continue", default="")
                    else:
                        _pick = alfard_select("which agent?", _agents + ["← back"])
                        if _pick and _pick != "← back":
                            ctx.invoke(service.commands["remove"], agent=_pick)
                            alfard_input("press enter to continue", default="")

                elif svc_pick == "view agent logs":
                    _agents = _svc_list_agents()
                    if not _agents:
                        console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                        alfard_input("press enter to continue", default="")
                    else:
                        _pick = alfard_select("which agent?", _agents + ["← back"])
                        if _pick and _pick != "← back":
                            ctx.invoke(service.commands["logs"], agent=_pick)

        elif selection == "manage memory":
            ctx.invoke(memory)
            alfard_input("press enter to continue", default="")
        elif selection == "list agents":
            ctx.invoke(list_agents)
            alfard_input("press enter to continue", default="")
        elif selection == "view status":
            ctx.invoke(status)
            alfard_input("press enter to continue", default="")
        elif selection == "view logs":
            ctx.invoke(log)
            alfard_input("press enter to continue", default="")
        elif selection == "run doctor":
            ctx.invoke(doctor)
            alfard_input("press enter to continue", default="")
        elif selection == "settings & setup":
            from alfard.paths import ALFARD_HOME
            import shutil
            sub = alfard_select(
                "settings & setup",
                [
                    "change provider / model / api key",
                    "change theme",
                    questionary.Separator(),
                    "re-run setup",
                    "reset alfard",
                    "uninstall alfard",
                    questionary.Separator(),
                    "← back",
                ],
            )
            if sub == "change provider / model / api key":
                from setup_alfard import run_provider_settings
                run_provider_settings()
                alfard_input("press enter to continue", default="")
            elif sub == "change theme":
                import yaml
                _cfg_path = ALFARD_HOME / "config" / "alfard.yaml"
                _cfg = {}
                if _cfg_path.exists():
                    with open(_cfg_path) as _f:
                        _cfg = yaml.safe_load(_f) or {}
                _current = _cfg.get("ui", {}).get("theme", "auto")
                theme_choice = alfard_select(
                    f"theme (current: {_current})",
                    ["auto", "light", "dark", "← back"],
                )
                if theme_choice and theme_choice != "← back":
                    if "ui" not in _cfg:
                        _cfg["ui"] = {}
                    if theme_choice == "auto":
                        _cfg["ui"].pop("theme", None)
                        if not _cfg["ui"]:
                            _cfg.pop("ui")
                    else:
                        _cfg["ui"]["theme"] = theme_choice
                    with open(_cfg_path, "w") as _f:
                        yaml.dump(_cfg, _f, default_flow_style=False, allow_unicode=True)
                    console.print()
                    if theme_choice == "auto":
                        console.print(f"  [{p.ok}]theme set to auto — will detect on next launch.[/]")
                    else:
                        console.print(f"  [{p.ok}]theme set to {theme_choice} — takes effect on next launch.[/]")
                    console.print()
                    alfard_input("press enter to continue", default="")
            elif sub == "re-run setup":
                ctx.invoke(setup)
            elif sub == "uninstall alfard":
                try:
                    ctx.invoke(uninstall)
                    return  # binary is gone — exit the menu loop
                except SystemExit:
                    pass  # user cancelled — back to settings
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
cli.add_command(headless)
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
cli.add_command(service)
cli.add_command(channel)
cli.add_command(uninstall)
cli.add_command(doctor)
cli.add_command(daemon)

if __name__ == "__main__":
    cli()
