"""Interactive first-run setup — asks the user which LLM provider they want, their API key or
localhost URL, and which model to use, then writes the result to config/alfard.yaml and .env."""

import os
import re
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

console = Console()

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


def run_setup():
    base_dir = Path(__file__).parent

    # 1. Welcome banner
    console.print(
        Panel(
            "[bold cyan]secure-by-default AI agent framework[/bold cyan]",
            title="[bold white]alfard[/bold white]",
            border_style="cyan",
            padding=(1, 4),
        )
    )

    # 2. Provider selection
    console.print("\n[bold]Select a provider:[/bold]")
    for num, name in PROVIDERS.items():
        tag = "  (local, no key needed)" if name in LOCAL_PROVIDERS else ""
        default_marker = "  [dim](default)[/dim]" if num == "1" else ""
        console.print(f"  {num}. {name}{tag}{default_marker}")

    provider_choice = Prompt.ask(
        "\nProvider",
        choices=list(PROVIDERS.keys()),
        default="1",
    )
    provider = PROVIDERS[provider_choice]
    console.print(f"[green]Selected:[/green] {provider}")

    # 3. API key or localhost URL
    api_key: str | None = None
    api_key_env: str | None = None
    base_url = PROVIDER_BASE_URLS[provider]

    if provider in CLOUD_PROVIDERS:
        api_key_env = PROVIDER_API_KEY_ENV[provider]
        api_key = Prompt.ask(f"\nEnter your {provider} API key", password=True)
        env_path = base_dir / ".env"
        _update_env_file(env_path, api_key_env, api_key)
        console.print(f"[green]API key written to[/green] {env_path.name} [dim]({api_key_env})[/dim]")
    else:
        console.print(f"\n[bold]Default localhost URL:[/bold] {base_url}")
        override = Prompt.ask("Base URL", default=base_url)
        base_url = override.rstrip("/")

    # 4. Model selection
    models = PROVIDER_MODELS[provider]
    console.print("\n[bold]Select a model:[/bold]")
    for num, name in models:
        console.print(f"  {num}. {name}")

    model_choices = [m[0] for m in models]
    model_choice = Prompt.ask(
        "Model",
        choices=model_choices,
        default=model_choices[0],
    )
    chosen_label = dict(models)[model_choice]

    if chosen_label == "custom":
        model = Prompt.ask("Enter custom model name")
    else:
        model = chosen_label

    # 5. Write config/alfard.yaml
    config_dir = base_dir / "config"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "alfard.yaml"

    config = {
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
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # 6. Summary table
    console.print()
    table = Table(title="Configuration Summary", border_style="cyan", show_header=True)
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("Provider", provider)
    table.add_row("Model", model)
    table.add_row("Base URL", base_url)
    table.add_row("API Key", "****" if api_key else "[dim]not required[/dim]")
    table.add_row("Config path", str(config_path.relative_to(base_dir)))

    console.print(table)

    console.print(
        Panel(
            "[bold green]Setup complete.[/bold green]  Run: [bold cyan]python main.py[/bold cyan]",
            border_style="green",
            padding=(0, 2),
        )
    )


if __name__ == "__main__":
    run_setup()
