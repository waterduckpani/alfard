"""Creates a new agent definition interactively."""

import re
from pathlib import Path
import click
from alfard.cli.help_formatter import AlfardCommand
import questionary
from alfard.agents.loader import (
    AGENTS_DIR, list_agents, list_available_skills, add_skill, remove_skill,
)
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, alfard_confirm, alfard_input, alfard_select, alfard_multiselect


_PROVIDER_LABELS = [
    "DuckDuckGo  (free, no setup)",
    "Brave       (free tier, API key required)",
    "SearXNG     (self-hosted, URL required)",
    "Fetch only  (no search, URL reading only)",
]

_PROVIDER_KEYS = {
    "DuckDuckGo  (free, no setup)": "duckduckgo",
    "Brave       (free tier, API key required)": "brave",
    "SearXNG     (self-hosted, URL required)": "searxng",
    "Fetch only  (no search, URL reading only)": "fetch_only",
}

_PROVIDER_LABELS_BY_KEY = {v: k for k, v in _PROVIDER_KEYS.items()}


def _web_wizard(agent_dir: Path, agent_name: str | None = None) -> bool:
    """Interactive wizard to configure or reconfigure web access for an agent.

    Returns True if web access is enabled after the wizard, False otherwise.
    If agent_name is given, automatically adds or removes the web_usage skill.
    """
    from alfard.web.config import WebConfig
    cfg = WebConfig(agent_dir)

    console.print()
    if not alfard_confirm("enable web access for this agent?", default=cfg.enabled):
        if cfg.enabled:
            cfg.update(enabled=False)
            cfg.save()
        if agent_name:
            remove_skill(agent_name, "web_usage")
        return False

    current_label = _PROVIDER_LABELS_BY_KEY.get(cfg.search_provider, _PROVIDER_LABELS[0])
    provider_label = alfard_select("search provider:", _PROVIDER_LABELS, default=current_label)
    if not provider_label:
        return False

    provider_key = _PROVIDER_KEYS[provider_label]
    brave_key = cfg.brave_api_key
    searxng_url = cfg.searxng_url

    if provider_key == "brave":
        brave_key = alfard_input("brave API key:", password=True).strip() or brave_key
    elif provider_key == "searxng":
        searxng_url = alfard_input(
            "searxng URL:",
            default=searxng_url or "",
            hint="e.g. http://localhost:8080",
        ).strip() or searxng_url

    cfg.update(
        enabled=True,
        search_provider=provider_key,
        brave_api_key=brave_key,
        searxng_url=searxng_url,
    )
    cfg.save()
    if agent_name:
        add_skill(agent_name, "web_usage")
    return True


@click.command(cls=AlfardCommand)
def create():
    """Create a new agent interactively."""

    console.print(f"\n[{p.fg_em}]create a new agent[/]\n")

    while True:
        name = alfard_input(
            "agent name",
            hint="lowercase, hyphens ok, e.g. my-agent   ·   leave blank to go back",
        ).strip().lower()
        if not name:
            return
        if not re.match(r'^[a-z0-9-]+$', name):
            console.print(f"  [{p.err}]name must be lowercase letters, numbers, or hyphens only.[/]")
            continue
        agent_dir = AGENTS_DIR / name
        if agent_dir.exists():
            console.print(f"  [{p.err}]agent '{name}' already exists.[/]")
            continue
        break

    description = alfard_input("what does this agent do?").strip()

    personality = alfard_input(
        "personality or tone",
        default="helpful and concise",
    ).strip()

    agent_dir.mkdir(parents=True, exist_ok=True)

    soul_content = f"""# {name}

## Purpose
{description}

## Personality
{personality}

## Rules
- Always be honest about what you can and cannot do.
- Never take irreversible actions without explicit user confirmation.
- Keep responses concise and focused on the task.
- If unsure, ask for clarification rather than guessing.
"""
    (agent_dir / "soul.md").write_text(soul_content, encoding="utf-8")

    (agent_dir / "brain.md").write_text(
        f"# {name} — knowledge\n\n",
        encoding="utf-8"
    )
    (agent_dir / "memory.md").write_text(
        f"# {name} — memory\n\n",
        encoding="utf-8"
    )

    # Step 1 — copy skills from an existing agent
    copied_skills: set[str] = set()
    agents_with_skills = [
        a for a in list_agents()
        if a != name and (AGENTS_DIR / a / "skills").exists()
        and any((AGENTS_DIR / a / "skills").glob("*.md"))
    ]
    if agents_with_skills:
        console.print()
        source = alfard_select(
            "copy skills from an existing agent? (optional)",
            ["skip"] + agents_with_skills,
            default="skip",
        )
        if source and source != "skip":
            src_skills_dir = AGENTS_DIR / source / "skills"
            dest_skills_dir = agent_dir / "skills"
            dest_skills_dir.mkdir(exist_ok=True)
            for skill_file in sorted(src_skills_dir.glob("*.md")):
                (dest_skills_dir / skill_file.name).write_text(
                    skill_file.read_text(encoding="utf-8"), encoding="utf-8"
                )
                copied_skills.add(skill_file.stem)

    # Step 2 — add skills from the global library
    available = list_available_skills()
    if available:
        choices = []
        for s in available:
            if s in copied_skills:
                choices.append(questionary.Choice(
                    s, value=s, checked=True, disabled="copied above"
                ))
            else:
                choices.append(questionary.Choice(s, value=s))
        console.print()
        selected = alfard_multiselect(
            "add skills from the library:",
            choices,
        )
        if selected:
            for s in selected:
                if s not in copied_skills:
                    add_skill(name, s)

    web_enabled = _web_wizard(agent_dir, name)
    if not web_enabled:
        console.print(f"[{p.fg_faint}]you can enable web access later via: alfard connect[/]")

    console.print()
    console.print(f"{dot('ok')} [{p.fg_dim}]alfard created {name}.[/]\n")
    console.print(f"[{p.fg_faint}]agents/{name}/[/]")
    console.print(f"  [{p.fg_dim}]soul.md[/]    — defines who your agent is")
    console.print(f"  [{p.fg_dim}]brain.md[/]   — permanent knowledge you give the agent")
    console.print(f"  [{p.fg_dim}]memory.md[/]  — managed automatically; do not edit by hand")
    console.print(f"\n  [{p.fg_em}]alfard edit {name} soul[/]    [{p.fg_faint}]open soul.md now[/]")
    console.print(f"  [{p.fg_em}]alfard run {name}[/]          [{p.fg_faint}]start chatting[/]")
