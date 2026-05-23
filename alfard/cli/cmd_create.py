"""Creates a new agent definition interactively."""

from pathlib import Path
import click
from alfard.cli.help_formatter import AlfardCommand
from alfard.agents.loader import AGENTS_DIR, add_skill, remove_skill
from alfard.cli.theme import p, console
from alfard.cli.components import alfard_confirm, alfard_input, alfard_select


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
    from alfard.cli.soul_wizard import run_soul_wizard
    run_soul_wizard()
