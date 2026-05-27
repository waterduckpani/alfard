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
from alfard.cli.cmd_headless import headless
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

    while True:
        console.clear()
        console.print()
        console.print(header_block(pkg_version("alfard")))
        console.print()
        selection = alfard_select("what would you like to do?", [
            "run an agent",
            "my agents",
            questionary.Separator(),
            "channels",
            "integrations",
            questionary.Separator(),
            "services",
            "cron jobs",
            questionary.Separator(),
            "status & logs",
            "settings",
            questionary.Separator(),
            "exit",
        ])

        if not selection or selection == "exit":
            return

        # ── run an agent ─────────────────────────────────────────────────────
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

        # ── my agents ────────────────────────────────────────────────────────
        elif selection == "my agents":
            while True:
                from alfard.agents.loader import list_agents as _list_agents_my
                agents = _list_agents_my()
                console.clear()
                console.print()
                console.print(header_block(pkg_version("alfard")))
                console.print()
                agent_choices = agents + [questionary.Separator(), "+ create new agent", "← back"]
                selected_agent = alfard_select("my agents", agent_choices)
                if not selected_agent or selected_agent == "← back":
                    break
                if selected_agent == "+ create new agent":
                    if ctx.invoke(create):
                        alfard_input("press enter to continue", default="")
                    continue
                # agent submenu
                while True:
                    console.clear()
                    console.print()
                    console.print(header_block(pkg_version("alfard")))
                    console.print()
                    agent_action = alfard_select(
                        selected_agent,
                        [
                            "run",
                            questionary.Separator(),
                            "edit",
                            "skills",
                            "mounts",
                            "memory",
                            questionary.Separator(),
                            "← back",
                        ],
                    )
                    if not agent_action or agent_action == "← back":
                        break
                    if agent_action == "run":
                        ctx.invoke(run, agent=selected_agent, no_mcp=False)
                    elif agent_action == "edit":
                        file_choice = alfard_select(
                            "which file?",
                            ["soul", "brain", "memory", "web", "← back"],
                        )
                        if file_choice and file_choice != "← back":
                            ctx.invoke(edit, agent=selected_agent, file=file_choice)
                            alfard_input("press enter to continue", default="")
                    elif agent_action == "skills":
                        ctx.invoke(skill)
                    elif agent_action == "mounts":
                        ctx.invoke(mount)
                    elif agent_action == "memory":
                        ctx.invoke(memory)
                        alfard_input("press enter to continue", default="")

        # ── channels ─────────────────────────────────────────────────────────
        elif selection == "channels":
            while True:
                console.clear()
                console.print()
                console.print(header_block(pkg_version("alfard")))
                console.print()
                ch_pick = alfard_select(
                    "channels",
                    [
                        "connect a channel",
                        "disconnect a channel",
                        questionary.Separator(),
                        "← back",
                    ],
                )
                if not ch_pick or ch_pick == "← back":
                    break
                if ch_pick == "connect a channel":
                    ctx.invoke(channel.commands["connect"])
                    alfard_input("press enter to continue", default="")
                elif ch_pick == "disconnect a channel":
                    load_env()
                    if not connected_channels():
                        console.print(f"\n[{p.fg_dim}]no channels connected.[/]")
                        console.print(f"[{p.fg_faint}]connect one first: alfard channel connect[/]")
                        alfard_input("press enter to continue", default="")
                    else:
                        ctx.invoke(channel.commands["disconnect"])
                        alfard_input("press enter to continue", default="")

        # ── integrations ─────────────────────────────────────────────────────
        elif selection == "integrations":
            while True:
                console.clear()
                console.print()
                console.print(header_block(pkg_version("alfard")))
                console.print()
                int_pick = alfard_select(
                    "integrations",
                    [
                        "connect an integration",
                        "disconnect an integration",
                        questionary.Separator(),
                        "← back",
                    ],
                )
                if not int_pick or int_pick == "← back":
                    break
                if int_pick == "connect an integration":
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
                elif int_pick == "disconnect an integration":
                    ctx.invoke(disconnect)
                    alfard_input("press enter to continue", default="")

        # ── services ─────────────────────────────────────────────────────────
        elif selection == "services":
            from alfard.agents.loader import list_agents as _svc_list_agents
            while True:
                console.clear()
                console.print()
                console.print(header_block(pkg_version("alfard")))
                console.print()
                svc_pick = alfard_select(
                    "services",
                    [
                        "list service status",
                        questionary.Separator(),
                        "install agent as service",
                        "start / stop / restart",
                        "remove service",
                        questionary.Separator(),
                        "view agent log",
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

                elif svc_pick == "start / stop / restart":
                    _agents = _svc_list_agents()
                    if not _agents:
                        console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                        continue
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

                elif svc_pick == "view agent log":
                    _agents = _svc_list_agents()
                    if not _agents:
                        console.print(f"[{p.fg_dim}]no agents found. create one with alfard create.[/]")
                        alfard_input("press enter to continue", default="")
                    else:
                        _pick = alfard_select("which agent?", _agents + ["← back"])
                        if _pick and _pick != "← back":
                            ctx.invoke(service.commands["logs"], agent=_pick)

        # ── cron jobs ────────────────────────────────────────────────────────
        elif selection == "cron jobs":
            while True:
                console.clear()
                console.print()
                console.print(header_block(pkg_version("alfard")))
                console.print()
                cron_pick = alfard_select(
                    "cron jobs",
                    [
                        "view cron jobs",
                        "add a cron job",
                        "remove a cron job",
                        questionary.Separator(),
                        "run scheduler",
                        "run job now",
                        questionary.Separator(),
                        "← back",
                    ],
                )
                if not cron_pick or cron_pick == "← back":
                    break
                if cron_pick == "view cron jobs":
                    ctx.invoke(cron.commands["list"])
                    alfard_input("press enter to continue", default="")
                elif cron_pick == "add a cron job":
                    ctx.invoke(cron.commands["add"])
                    alfard_input("press enter to continue", default="")
                elif cron_pick == "remove a cron job":
                    ctx.invoke(cron.commands["remove"])
                    alfard_input("press enter to continue", default="")
                elif cron_pick == "run scheduler":
                    ctx.invoke(cron.commands["run"])
                elif cron_pick == "run job now":
                    ctx.invoke(cron.commands["now"])
                    alfard_input("press enter to continue", default="")

        # ── status & logs ────────────────────────────────────────────────────
        elif selection == "status & logs":
            while True:
                console.clear()
                console.print()
                console.print(header_block(pkg_version("alfard")))
                console.print()
                sl_pick = alfard_select(
                    "status & logs",
                    [
                        "view status",
                        "view audit log",
                        "run doctor",
                        questionary.Separator(),
                        "← back",
                    ],
                )
                if not sl_pick or sl_pick == "← back":
                    break
                if sl_pick == "view status":
                    ctx.invoke(status)
                    alfard_input("press enter to continue", default="")
                elif sl_pick == "view audit log":
                    ctx.invoke(log)
                    alfard_input("press enter to continue", default="")
                elif sl_pick == "run doctor":
                    ctx.invoke(doctor)
                    alfard_input("press enter to continue", default="")

        # ── settings ─────────────────────────────────────────────────────────
        elif selection == "settings":
            from alfard.paths import ALFARD_HOME
            import shutil
            while True:
                console.clear()
                console.print()
                console.print(header_block(pkg_version("alfard")))
                console.print()
                sub = alfard_select(
                    "settings",
                    [
                        "change provider",
                        "change theme",
                        questionary.Separator(),
                        "reset alfard",
                        "uninstall alfard",
                        questionary.Separator(),
                        "← back",
                    ],
                )
                if not sub or sub == "← back":
                    break
                if sub == "change provider":
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
                elif sub == "uninstall alfard":
                    try:
                        ctx.invoke(uninstall)
                        return  # binary is gone — exit the menu loop
                    except SystemExit:
                        pass  # user cancelled — back to settings


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
