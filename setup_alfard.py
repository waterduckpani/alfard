"""Interactive first-run setup — gets alfard working from scratch."""

import os
import re
import sys
import shutil
import subprocess
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from alfard.cli import theme

console = Console()

BASE_DIR = Path(__file__).parent

PROVIDERS = {
    "1": "openrouter",
    "2": "openai",
    "3": "anthropic",
    "4": "ollama",
    "5": "lmstudio",
}

CLOUD_PROVIDERS = {"openrouter", "openai", "anthropic"}
LOCAL_PROVIDERS = {"ollama", "lmstudio"}

PROVIDER_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "ollama": "http://localhost:11434",
    "lmstudio": "http://localhost:1234/v1",
}

PROVIDER_API_KEY_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

PROVIDER_MODELS = {
    "openrouter": [
        ("1", "openrouter/auto"),
        ("2", "anthropic/claude-sonnet-4-5"),
        ("3", "google/gemini-2.5-pro"),
        ("4", "custom"),
    ],
    "openai": [
        ("1", "gpt-4o"),
        ("2", "gpt-4o-mini"),
        ("3", "o3-mini"),
        ("4", "custom"),
    ],
    "anthropic": [
        ("1", "claude-sonnet-4-5"),
        ("2", "claude-opus-4-5"),
        ("3", "claude-haiku-4-5-20251001"),
        ("4", "custom"),
    ],
    "ollama": [
        ("1", "llama3.2"),
        ("2", "mistral"),
        ("3", "qwen2.5-coder"),
        ("4", "custom"),
    ],
    "lmstudio": [
        ("1", "custom"),
    ],
}


def _update_env_file(env_path: Path, key: str, value: str) -> None:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    new_line = f"{key}={value}"
    if env_path.exists():
        content = env_path.read_text()
        if pattern.search(content):
            content = pattern.sub(new_line, content)
        else:
            content = content.rstrip("\n") + f"\n{new_line}\n"
        env_path.write_text(content)
    else:
        env_path.write_text(f"{new_line}\n")


def run_setup() -> None:

    # ── 1. WELCOME ────────────────────────────────────────────────────────────
    console.print(Panel(
        "local AI agents, done right.\n\n"
        "Secure by default. Every action logged.\n"
        "Your data stays on your machine.\n\n"
        "This wizard sets up alfard in about 2 minutes.",
        title="alfard",
        border_style=theme.PRIMARY,
        padding=(1, 4),
    ))

    # Dependency check
    from alfard.setup.dependencies import ensure_dependencies
    if not ensure_dependencies():
        console.print(Panel(
            f"[{theme.ERROR}]Setup cannot continue — missing required dependencies.[/{theme.ERROR}]\n\n"
            "Please install Node.js from https://nodejs.org and re-run alfard setup.",
            border_style=theme.PANEL_ERROR
        ))
        return

    # ── 3. LLM PROVIDER ───────────────────────────────────────────────────────
    console.print(f"\n[bold {theme.HEADING}]LLM Provider[/bold {theme.HEADING}]")
    console.print("Which provider do you want to use?\n")

    for num, name in PROVIDERS.items():
        tag = "  (local, no key needed)" if name in LOCAL_PROVIDERS else ""
        default_marker = f"  [{theme.DIM}](default)[/{theme.DIM}]" if num == "1" else ""
        console.print(f"  {num}. {name}{tag}{default_marker}")

    provider_choice = Prompt.ask(
        "\nProvider", choices=list(PROVIDERS.keys()), default="1"
    )
    provider = PROVIDERS[provider_choice]

    api_key: str | None = None
    api_key_env: str | None = None
    base_url = PROVIDER_BASE_URLS[provider]

    if provider in CLOUD_PROVIDERS:
        api_key_env = PROVIDER_API_KEY_ENV[provider]
        api_key = Prompt.ask(f"\nEnter your {provider} API key", password=True)
        _update_env_file(BASE_DIR / ".env", api_key_env, api_key)
    else:
        console.print(f"\n[bold]Default localhost URL:[/bold] {base_url}")
        override = Prompt.ask("Base URL", default=base_url)
        base_url = override.rstrip("/")

    models = PROVIDER_MODELS[provider]
    console.print("\n[bold]Select a model:[/bold]")
    for num, name in models:
        console.print(f"  {num}. {name}")

    model_choices = [m[0] for m in models]
    model_choice = Prompt.ask("Model", choices=model_choices, default=model_choices[0])
    chosen_label = dict(models)[model_choice]

    if chosen_label == "custom":
        model = Prompt.ask("Enter custom model name")
    else:
        model = chosen_label

    config_dir = BASE_DIR / "config"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "alfard.yaml"

    config_data = {
        "provider": {
            "name": provider,
            "model": model,
            "base_url": base_url,
            "api_key_env": api_key_env,
        },
        "approval_gate": {
            "enabled": True,
            "mode": "cli",
        },
        "audit": {
            "enabled": True,
            "log_path": "logs/audit.jsonl",
        },
    }
    with config_path.open("w") as f:
        yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

    console.print(
        f"\n[{theme.SUCCESS}]{theme.ICON_OK} Provider configured: {provider} / {model}[/{theme.SUCCESS}]"
    )

    # ── 4. CREATE FIRST AGENT ─────────────────────────────────────────────────
    console.print(f"\n[bold {theme.HEADING}]Create your first agent[/bold {theme.HEADING}]")
    console.print("Agents are AI assistants with their own identity and skills.\n")

    from alfard.agents.loader import AGENTS_DIR

    agent_name = ""
    while True:
        agent_name = Prompt.ask("Agent name").strip().lower()
        if not agent_name:
            console.print(f"[{theme.ERROR}]Name cannot be empty.[/{theme.ERROR}]")
            continue
        if not re.match(r'^[a-z0-9-]+$', agent_name):
            console.print(
                f"[{theme.ERROR}]Name must be lowercase letters, numbers, or hyphens only.[/{theme.ERROR}]"
            )
            continue
        break

    agent_dir = AGENTS_DIR / agent_name
    if agent_dir.exists():
        console.print(
            f"[{theme.WARNING}]Agent '{agent_name}' already exists — using existing agent.[/{theme.WARNING}]"
        )
    else:
        description = Prompt.ask("What does this agent do?").strip()
        personality = Prompt.ask(
            "Personality or tone",
            default="helpful and concise",
        ).strip()

        agent_dir.mkdir(parents=True, exist_ok=True)
        soul_content = f"""# {agent_name}

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
        (agent_dir / "brain.md").write_text(f"# {agent_name} — knowledge\n\n", encoding="utf-8")
        (agent_dir / "memory.md").write_text(f"# {agent_name} — memory\n\n", encoding="utf-8")
        console.print(f"[{theme.SUCCESS}]{theme.ICON_OK} Agent '{agent_name}' created[/{theme.SUCCESS}]")

    # ── 5. CONNECT INTEGRATION (optional) ─────────────────────────────────────
    console.print(f"\n[bold {theme.HEADING}]Connect an integration (optional)[/bold {theme.HEADING}]")
    console.print("Connect Notion, Gmail, GitHub, Slack and more.\n")

    do_connect = Prompt.ask("Connect an integration now?", choices=["y", "n"], default="n")

    if do_connect == "y":
        from alfard.integrations.catalogue import CATALOGUE, AUTH_APIKEY
        from alfard.cli.cmd_connect import _connect_apikey, _connect_oauth

        names = list(CATALOGUE.keys())
        for i, key in enumerate(names, start=1):
            info = CATALOGUE[key]
            console.print(
                f"  {i}. {info['display_name']}  "
                f"[{theme.DIM}]{info['description']}[/{theme.DIM}]"
            )

        raw = Prompt.ask("\nEnter number")
        try:
            choice_idx = int(raw) - 1
        except ValueError:
            choice_idx = -1

        if 0 <= choice_idx < len(names):
            chosen = names[choice_idx]
            info = CATALOGUE[chosen]
            if info["auth"] == AUTH_APIKEY:
                _connect_apikey(chosen, info)
            else:
                _connect_oauth(chosen, info)
        else:
            console.print(f"[{theme.WARNING}]Invalid choice — skipping.[/{theme.WARNING}]")
    else:
        console.print(
            f"[{theme.DIM}]You can connect integrations later: alfard connect[/{theme.DIM}]"
        )

    # ── 6. DONE ───────────────────────────────────────────────────────────────
    console.print(Panel(
        f"[{theme.SUCCESS}]{theme.ICON_OK} alfard is ready.[/{theme.SUCCESS}]\n\n"
        f"Your agent: [bold]{agent_name}[/bold]\n\n"
        "What to do next:\n"
        f"  alfard run {agent_name}     start chatting\n"
        "  alfard connect              connect integrations\n"
        "  alfard cron add             schedule tasks\n"
        "  alfard --help               see all commands",
        border_style=theme.PANEL_SUCCESS,
    ))


if __name__ == "__main__":
    run_setup()
