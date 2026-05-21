"""CLI command for managing agent skills."""

import os
import re
import subprocess

import click

from alfard.agents.loader import (
    AgentLoader, list_agents, list_available_skills,
    add_skill, remove_skill,
)
from alfard.paths import USER_SKILLS_DIR
from alfard.cli.theme import p, c, console
from alfard.cli.components import (
    dot, alfard_table,
    alfard_select, alfard_multiselect, alfard_confirm, alfard_input,
)


def _ask_agent(prompt: str) -> str | None:
    agents = list_agents()
    if not agents:
        console.print(f"[{p.err}]no agents found. run alfard create first.[/]")
        return None
    return alfard_select(prompt, agents)


@click.group(invoke_without_command=True)
@click.pass_context
def skill(ctx: click.Context):
    """Manage skills — teach agents how to use integrations correctly."""
    if ctx.invoked_subcommand is not None:
        return

    import questionary

    while True:
        console.clear()
        console.print(f"\n[{p.fg_em}]manage skills[/]\n")
        action = alfard_select("what would you like to do?", [
            "list skills",
            "add skills to an agent",
            "remove skills from an agent",
            "create a new skill",
            questionary.Separator(),
            "← back",
        ])
        if not action or action == "← back":
            return

        if action == "list skills":
            ctx.invoke(list_skills)
        elif action == "add skills to an agent":
            ctx.invoke(add)
        elif action == "remove skills from an agent":
            ctx.invoke(remove)
        elif action == "create a new skill":
            ctx.invoke(create)
        alfard_input("press enter to continue", default="")


@skill.command(name="list")
@click.argument("agent", required=False)
def list_skills(agent: str | None):
    """List skills globally or for a specific agent."""
    available = list_available_skills()
    if not available:
        console.print(
            f"[{p.fg_faint}]no skills in library. run alfard skill create to add one.[/]"
        )
        return

    if agent:
        if agent not in list_agents():
            console.print(f"[{p.err}]agent '{agent}' not found.[/]")
            raise SystemExit(1)
        loader = AgentLoader(agent)
        active = set(loader.get_agent_skills())
        rows = []
        for s in available:
            status = c("ok", "active") if s in active else c("fg_faint", "not added")
            rows.append({"skill": c("fg_em", s), "status": status})
        console.print(f"\n[{p.fg_dim}]skills — {agent}[/]")
        console.print(alfard_table(
            [{"header": "skill", "key": "skill"}, {"header": "status", "key": "status"}],
            rows,
        ))
        console.print()
    else:
        agents = list_agents()
        agent_skill_map: dict[str, set[str]] = {}
        for a in agents:
            try:
                agent_skill_map[a] = set(AgentLoader(a).get_agent_skills())
            except Exception:
                agent_skill_map[a] = set()

        rows = []
        for s in available:
            has = [a for a in agents if s in agent_skill_map.get(a, set())]
            agents_str = c("fg_dim", ", ".join(has)) if has else c("fg_faint", "none")
            rows.append({"skill": c("fg_em", s), "agents": agents_str})
        console.print(f"\n[{p.fg_dim}]skills[/]")
        console.print(alfard_table(
            [{"header": "skill", "key": "skill"}, {"header": "agents", "key": "agents"}],
            rows,
        ))
        console.print()


@skill.command(name="add")
@click.argument("agent", required=False)
def add(agent: str | None):
    """Add skills to an agent interactively."""
    console.print(f"\n[{p.fg_em}]add skills[/]\n")

    if not agent:
        agent = _ask_agent("add skills to which agent?")
        if not agent:
            raise SystemExit(1)
    elif agent not in list_agents():
        console.print(f"[{p.err}]agent '{agent}' not found.[/]")
        raise SystemExit(1)

    available = list_available_skills()
    if not available:
        console.print(
            f"[{p.fg_faint}]no skills in library. run alfard skill create first.[/]"
        )
        return

    loader = AgentLoader(agent)
    active = set(loader.get_agent_skills())
    addable = [s for s in available if s not in active]

    if not addable:
        console.print(f"[{p.fg_faint}]{agent} already has all available skills.[/]")
        return

    rows = []
    for s in available:
        status = c("ok", "active") if s in active else c("fg_faint", "not added")
        rows.append({"skill": c("fg_em", s), "status": status})
    table = alfard_table(
        [{"header": "skill", "key": "skill"}, {"header": "status", "key": "status"}],
        rows,
    )
    console.print(table)
    console.print()

    selected = alfard_multiselect(
        f"select skills to add to {agent}:",
        addable,
    )

    if not selected:
        console.print(f"[{p.fg_faint}]no skills selected.[/]")
        return

    console.print()
    console.print(f"[{p.fg_dim}]adding to {agent}:[/]")
    for s in selected:
        console.print(f"  [{p.fg_faint}]{s}[/]")
    console.print()

    if not alfard_confirm("apply?", default=True):
        console.print(f"[{p.fg_faint}]cancelled.[/]")
        return

    added, failed = [], []
    for s in selected:
        (added if add_skill(agent, s) else failed).append(s)

    if added:
        console.print(f"\n{dot('ok')} [{p.fg_dim}]added {len(added)} skill(s) to {agent}.[/]")
        for s in added:
            console.print(f"  [{p.fg_faint}]{s}[/]")
        console.print(f"[{p.fg_faint}]restart the agent for changes to take effect.[/]")
    if failed:
        console.print(f"  [{p.warn}]could not add: {', '.join(failed)}[/]")


@skill.command(name="remove")
@click.argument("agent", required=False)
def remove(agent: str | None):
    """Remove skills from an agent interactively."""
    console.print(f"\n[{p.fg_em}]remove skills[/]\n")

    if not agent:
        agent = _ask_agent("remove skills from which agent?")
        if not agent:
            raise SystemExit(1)
    elif agent not in list_agents():
        console.print(f"[{p.err}]agent '{agent}' not found.[/]")
        raise SystemExit(1)

    loader = AgentLoader(agent)
    active = loader.get_agent_skills()

    if not active:
        console.print(f"[{p.fg_faint}]{agent} has no active skills.[/]")
        return

    rows = [{"skill": c("fg_em", s)} for s in active]
    table = alfard_table([{"header": f"active skills — {agent}", "key": "skill"}], rows)
    console.print(table)
    console.print()

    to_remove = alfard_multiselect(
        f"select skills to remove from {agent}:",
        active,
    )

    if not to_remove:
        console.print(f"[{p.fg_faint}]no skills selected.[/]")
        return

    console.print()
    console.print(f"[{p.fg_dim}]removing from {agent}:[/]")
    for s in to_remove:
        console.print(f"  [{p.fg_faint}]{s}[/]")
    console.print()

    if not alfard_confirm("apply?", default=False):
        console.print(f"[{p.fg_faint}]cancelled.[/]")
        return

    removed = [s for s in to_remove if remove_skill(agent, s)]
    console.print(
        f"{dot('ok')} [{p.fg_dim}]removed {len(removed)} skill(s) from {agent}.[/]"
    )


@skill.command(name="create")
def create():
    """Scaffold a new skill and open it in your editor."""
    console.print(f"\n[{p.fg_em}]create a new skill[/]\n")

    while True:
        name = alfard_input("skill name", hint="lowercase, hyphens ok   ·   leave blank to go back").strip().lower()
        if not name:
            return
        if not re.match(r'^[a-z0-9-]+$', name):
            console.print(
                f"  [{p.err}]lowercase letters, numbers, and hyphens only.[/]"
            )
            continue
        dest = USER_SKILLS_DIR / f"{name}.md"
        if dest.exists():
            console.print(
                f"  [{p.warn}]'{name}' already exists at {dest}[/]"
            )
            if not alfard_confirm("overwrite?", default=False):
                continue
        break

    description = alfard_input("one-line description:").strip()

    agents = list_agents()
    choices = ["none — add later"] + agents
    target = alfard_select(
        "add to an agent now?",
        choices,
        default="none — add later",
    )
    if target is None or target == "none — add later":
        target = None

    USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    skeleton = (
        f"# {name.capitalize()} skill\n\n"
        f"{description}\n\n"
        f"## How it works\n\n\n"
        f"## Rules\n\n\n"
        f"## Common mistakes to avoid\n\n"
    )
    dest.write_text(skeleton, encoding="utf-8")

    if target:
        add_skill(target, name)

    console.print(f"\n{dot('ok')} [{p.fg_dim}]skill '{name}' created.[/]")
    if target:
        console.print(f"[{p.fg_faint}]added to {target}.[/]")
    console.print(f"[{p.fg_faint}]{dest}[/]")

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
    console.print(f"\n[{p.fg_dim}]opening in {editor}...[/]")
    subprocess.run([editor, str(dest)])
