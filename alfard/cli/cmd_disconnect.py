"""CLI command to disconnect an integration from alfard."""

import click
import yaml
import shutil
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from alfard.cli import theme
from alfard.integrations.catalogue import CATALOGUE
from alfard.agents.loader import list_agents, AGENTS_DIR

console = Console()
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
_INTEGRATIONS_PATH = Path(__file__).parent.parent.parent / "config" / "integrations.yaml"

@click.command()
@click.argument("integration")
def disconnect(integration: str):
    """Disconnect an integration and remove it from all agents.

    Removes the integration from integrations.yaml, clears the
    credential from .env, and removes the skill from all agents.

    \b
    Example:
      alfard disconnect notion
      alfard disconnect gmail
    """
    integration = integration.lower().strip()

    if integration not in CATALOGUE:
        console.print(Panel(
            f"[{theme.ERROR}]Unknown integration: '{integration}'[/{theme.ERROR}]\n\n"
            f"Run [bold]alfard connect[/bold] to see connected integrations.",
            border_style=theme.PANEL_ERROR
        ))
        raise SystemExit(1)

    info = CATALOGUE[integration]
    display = info["display_name"]

    # Confirm
    confirm = Prompt.ask(
        f"Disconnect [bold]{display}[/bold]? "
        f"This removes it from all agents. [y/n]",
        choices=["y", "n"],
        default="n"
    )
    if confirm != "y":
        console.print(f"[{theme.DIM}]Cancelled.[/{theme.DIM}]")
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
            console.print(f"[{theme.DIM}]✓ Removed from integrations.yaml[/{theme.DIM}]")
            removed_anything = True

    # 2. Remove credential from .env
    credential_env = info.get("credential_env", "")
    if credential_env and _ENV_PATH.exists():
        content = _ENV_PATH.read_text(encoding="utf-8")
        import re
        pattern = re.compile(
            rf"^{re.escape(credential_env)}=.*$\n?", re.MULTILINE
        )
        new_content = pattern.sub("", content)
        if new_content != content:
            _ENV_PATH.write_text(new_content, encoding="utf-8")
            console.print(
                f"[{theme.DIM}]✓ Removed {credential_env} from .env[/{theme.DIM}]"
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
            f"[{theme.DIM}]✓ Skill removed from: "
            f"{', '.join(skill_removed_from)}[/{theme.DIM}]"
        )
        removed_anything = True

    # 4. Special handling for gws-based integrations
    # Do NOT delete gws credentials — user may still need them for gdrive
    # Just inform them
    if integration in ("gmail", "gdrive"):
        console.print(
            f"[{theme.DIM}]Note: gws credentials kept at ~/.config/gws/\n"
            f"To fully remove Google auth run: rm -rf ~/.config/gws[/{theme.DIM}]"
        )

    if removed_anything:
        console.print(Panel(
            f"[bold {theme.SUCCESS}]{display} disconnected.[/bold {theme.SUCCESS}]\n\n"
            f"Run [bold]alfard status[/bold] to confirm.",
            border_style=theme.PANEL_SUCCESS
        ))
    else:
        console.print(
            f"[{theme.DIM}]{display} was not connected.[/{theme.DIM}]"
        )
