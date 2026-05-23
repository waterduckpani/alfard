"""Creates a new agent definition interactively."""

import re
from pathlib import Path
import click
from alfard.cli.help_formatter import AlfardCommand
import questionary
from alfard.agents.loader import AGENTS_DIR, add_skill, remove_skill, list_available_skills
from alfard.cli.theme import p, console
from alfard.cli.components import g, alfard_confirm, alfard_input, alfard_select, alfard_multiselect


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


_ESSENTIAL_SKILLS = [
    "memory", "tasks", "projects", "research",
    "reasoning", "communication", "debugging",
]

_TONE_OPTIONS = ["professional", "friendly", "direct", "casual", "custom"]

_LENGTH_OPTIONS = [
    "concise (1-3 sentences)",
    "balanced",
    "thorough",
    "ask me each time",
]

_UNCERTAIN_OPTIONS = [
    "say so and stop",
    "say so and search",
    "make its best guess and flag it",
]


def _section(title: str) -> None:
    fill = g["h"] * max(0, 44 - len(title) - 4)
    console.print(f"\n[{p.fg_dim}]{g['h']}{g['h']} {title} {fill}[/]\n")


@click.command(cls=AlfardCommand)
def create():
    """Create a new agent interactively."""

    console.print(f"\n[{p.fg_em}]create a new agent[/]\n")

    # ── Section 1 — Identity ──────────────────────────────────────────────────

    _section("Identity")

    while True:
        name = alfard_input(
            "what is your agent's name?",
            hint="lowercase, hyphens ok  ·  blank to cancel",
        ).strip().lower()
        if not name:
            return
        if not re.match(r"^[a-z0-9-]+$", name):
            console.print(f"  [{p.err}]name must be lowercase letters, numbers, or hyphens only.[/]")
            continue
        agent_dir = AGENTS_DIR / name
        if agent_dir.exists():
            console.print(f"  [{p.err}]agent '{name}' already exists.[/]")
            continue
        break

    description = alfard_input(
        "describe your agent in one sentence — what is it for?",
    ).strip()

    tone_choice = alfard_select("what tone should it have?", _TONE_OPTIONS)
    if tone_choice is None:
        return
    if tone_choice == "custom":
        tone = alfard_input("describe the tone in your own words:").strip() or "professional"
    else:
        tone = tone_choice

    # ── Section 2 — Expertise ─────────────────────────────────────────────────

    _section("Expertise")

    knows_deeply = alfard_input(
        "what domains or topics should it know deeply?",
        hint="optional — press enter to skip",
    ).strip()

    stays_out_of = alfard_input(
        "what domains should it stay out of entirely?",
        hint="optional — press enter to skip",
    ).strip()

    # ── Section 3 — Communication ─────────────────────────────────────────────

    _section("Communication")

    length_choice = alfard_select(
        "how long should responses be by default?", _LENGTH_OPTIONS
    )
    if length_choice is None:
        return
    response_length = length_choice

    formatting = alfard_input(
        "any formatting rules?",
        hint="optional — e.g. always use bullet points, never use headers",
    ).strip()

    # ── Section 4 — When uncertain ────────────────────────────────────────────

    _section("When uncertain")

    uncertain_choice = alfard_select(
        "when it doesn't know something, should it:", _UNCERTAIN_OPTIONS
    )
    if uncertain_choice is None:
        return
    uncertain = uncertain_choice

    # ── Section 5 — About you ─────────────────────────────────────────────────

    _section("About you  (optional — press enter to skip)")

    user_name = alfard_input("your name?").strip()
    user_pref = alfard_input("one thing about how you like to work?").strip()

    # ── Section 6 — Skills ────────────────────────────────────────────────────

    _section("Skills  (optional — space to toggle, enter to confirm)")

    available = list_available_skills()
    extra_skills: list[str] = []
    if available:
        choices = [questionary.Choice(s, value=s) for s in available]
        extra_skills = alfard_multiselect("add skills from the library:", choices)

    # ── Create agent directory ────────────────────────────────────────────────

    agent_dir.mkdir(parents=True, exist_ok=True)

    # ── Generate soul.md ──────────────────────────────────────────────────────

    lines: list[str] = [
        "# Soul",
        "",
        "## Identity",
        f"Name: {name}",
        f"Purpose: {description or '—'}",
        f"Tone: {tone}",
        "",
        "## Expertise",
        f"Knows deeply: {knows_deeply or '—'}",
        f"Stays out of: {stays_out_of or '—'}",
        "",
        "## Communication",
        f"Response length: {response_length}",
        f"Formatting: {formatting or '—'}",
        "",
        "## Behaviour",
        f"When uncertain: {uncertain}",
        "",
        "## Core rules",
        "- Never modify soul.md",
        "- Never store API keys, passwords, or tokens in memory",
        "- Always prefer the reversible path when options exist",
    ]

    if stays_out_of:
        lines.append(f"- Do not engage with: {stays_out_of}")
    if uncertain == "say so and stop":
        lines.append("- When uncertain, acknowledge the limit clearly and stop")
    elif uncertain == "say so and search":
        lines.append("- When uncertain, say so then use search to find the answer")
    elif "best guess" in uncertain:
        lines.append("- When uncertain, give a best guess but always flag it explicitly")

    (agent_dir / "soul.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ── brain.md stub ─────────────────────────────────────────────────────────

    (agent_dir / "brain.md").write_text(f"# {name} — knowledge\n\n", encoding="utf-8")

    # ── Write user facts to brain.db ──────────────────────────────────────────

    if user_name or user_pref:
        try:
            from alfard.memory.store import VectorStore
            store = VectorStore(agent_dir / "brain.db")
            if user_name:
                store.store(
                    f"User's name is {user_name}",
                    memory_type="fact",
                    source="user_explicit",
                    confidence=1.0,
                    importance=0.8,
                )
            if user_pref:
                store.store(
                    user_pref,
                    memory_type="preference",
                    source="user_explicit",
                    confidence=1.0,
                    importance=0.8,
                )
        except Exception:
            pass

    # ── Add selected skills ───────────────────────────────────────────────────

    for skill in extra_skills:
        add_skill(name, skill)

    # ── Completion ────────────────────────────────────────────────────────────

    console.print()
    console.print(f"[{p.ok}]{g['check']}[/] soul.md written")
    skills_list = ", ".join(_ESSENTIAL_SKILLS)
    console.print(f"[{p.ok}]{g['check']}[/] Essential skills included: {skills_list}")
    console.print(f"[{p.fg_faint}]  Edit anytime: alfard edit {name} soul[/]")
