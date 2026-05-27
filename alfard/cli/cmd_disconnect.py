"""CLI command to disconnect an integration from alfard."""

import re
import os
import click
from alfard.cli.help_formatter import AlfardCommand
import yaml
from pathlib import Path
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, error_block, alfard_confirm, alfard_select
from alfard.integrations.catalogue import CATALOGUE
from alfard.agents.loader import list_agents, AGENTS_DIR
from alfard.paths import ALFARD_HOME, load_env

_ENV_PATH = ALFARD_HOME / ".env"
_INTEGRATIONS_PATH = ALFARD_HOME / "config" / "integrations.yaml"


def _connected_integrations() -> list[str]:
    connected = []
    if _INTEGRATIONS_PATH.exists():
        with open(_INTEGRATIONS_PATH) as f:
            data = yaml.safe_load(f) or {}
        connected.extend(s.get("name", "") for s in data.get("servers", []) if s.get("name"))
    gws_creds = Path.home() / ".config" / "gws" / "credentials.enc"
    if gws_creds.exists():
        for name in ("gmail", "gdrive"):
            if name not in connected:
                connected.append(name)
    load_env()
    if os.environ.get("SLACK_BOT_TOKEN") and "slack" not in connected:
        connected.append("slack")
    from alfard.web.config import WebConfig
    if any(WebConfig(AGENTS_DIR / a).enabled for a in list_agents()):
        connected.append("web-access")
    return connected


def _disconnect_web_access() -> None:
    """Disable web access and remove web_usage skill from chosen agent(s)."""
    from alfard.web.config import WebConfig
    from alfard.agents.loader import remove_skill

    agents_with_web = [a for a in list_agents() if WebConfig(AGENTS_DIR / a).enabled]
    if not agents_with_web:
        console.print(f"[{p.fg_dim}]no agents have web access enabled.[/]")
        return

    choices = agents_with_web + (["all agents"] if len(agents_with_web) > 1 else [])
    agent_choice = alfard_select("which agent?", choices, default=choices[0])
    if not agent_choice:
        return

    if not alfard_confirm("disable web access?", default=False):
        console.print(f"[{p.fg_dim}]cancelled.[/]")
        return

    targets = agents_with_web if agent_choice == "all agents" else [agent_choice]
    for agent_name in targets:
        cfg = WebConfig(AGENTS_DIR / agent_name)
        cfg.update(enabled=False)
        cfg.save()
        remove_skill(agent_name, "web_usage")

    label = "all agents" if agent_choice == "all agents" else agent_choice
    console.print(f"\n{dot('ok')} [{p.fg_dim}]web access disabled for {label}.[/]")


@click.command(cls=AlfardCommand)
@click.argument("integration", required=False)
def disconnect(integration: str | None):
    """Disconnect an integration and remove it from all agents.

    Removes the integration from integrations.yaml, clears the
    credential from .env, and removes the skill from all agents.

    \b
    Example:
      alfard disconnect notion
      alfard disconnect gmail
    """
    if not integration:
        connected = _connected_integrations()
        if not connected:
            console.print(f"[{p.fg_faint}]no integrations connected.[/]")
            return
        integration = alfard_select("which integration to disconnect?", connected)
        if not integration:
            return

    integration = integration.lower().strip()

    if integration in ("web access", "web-access"):
        _disconnect_web_access()
        return

    if integration not in CATALOGUE:
        console.print(error_block(
            agent="alfard disconnect",
            state="failed",
            headline=f"unknown integration: '{integration}'",
            explanation="run alfard connect to see connected integrations.",
        ))
        return

    info = CATALOGUE[integration]
    display = info["display_name"]

    console.print(f"\n{dot('warn')} [{p.warn}]{display}[/]")
    if not alfard_confirm(
        "disconnect? this removes it from all agents.",
        default=False,
    ):
        console.print(f"[{p.fg_dim}]cancelled.[/]")
        return

    removed_anything = False

    # 1. Remove from integrations.yaml
    if _INTEGRATIONS_PATH.exists():
        with open(_INTEGRATIONS_PATH) as f:
            data = yaml.safe_load(f) or {"servers": []}
        original_count = len(data.get("servers", []))
        data["servers"] = [
            s for s in data.get("servers", [])
            if s.get("name") != integration
        ]
        if len(data["servers"]) < original_count:
            with open(_INTEGRATIONS_PATH, "w") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
            console.print(f"  {dot('ok')} [{p.fg_dim}]removed from integrations.yaml[/]")
            removed_anything = True

    # 2. Remove credential from .env
    credential_env = info.get("credential_env", "")
    if credential_env and _ENV_PATH.exists():
        content = _ENV_PATH.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"^{re.escape(credential_env)}=.*$\n?", re.MULTILINE
        )
        new_content = pattern.sub("", content)
        if new_content != content:
            _ENV_PATH.write_text(new_content, encoding="utf-8")
            console.print(
                f"  {dot('ok')} [{p.fg_dim}]removed {credential_env} from .env[/]"
            )
            removed_anything = True

    # 3. Remove skill from all agents
    skill_removed_from = []
    for agent_name in list_agents():
        skill_path = AGENTS_DIR / agent_name / "skills" / f"{integration}.md"
        if skill_path.exists():
            skill_path.unlink()
            skill_removed_from.append(agent_name)

    if skill_removed_from:
        console.print(
            f"  {dot('ok')} [{p.fg_dim}]skill removed from: "
            f"{', '.join(skill_removed_from)}[/]"
        )
        removed_anything = True

    # 4. Special handling for gws-based integrations
    if integration in ("gmail", "gdrive"):
        console.print(
            f"[{p.fg_dim}]note: gws credentials kept at ~/.config/gws/[/]\n"
            f"[{p.fg_faint}]to fully remove google auth run: rm -rf ~/.config/gws[/]"
        )

    if removed_anything:
        console.print(f"\n{dot('ok')} [{p.fg_em}]{display}[/] [{p.fg_dim}]disconnected.[/]")
    else:
        console.print(f"[{p.fg_dim}]{display} was not connected.[/]")
