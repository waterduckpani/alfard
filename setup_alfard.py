"""Interactive first-run setup — gets alfard working from scratch."""

import os
import re
import sys
import shutil
import subprocess
from pathlib import Path

import yaml
from alfard.paths import ALFARD_HOME
from alfard.cli.theme import p, c, console
from alfard.cli.components import (
    header_block, dot, error_block,
    alfard_select, alfard_multiselect, alfard_confirm, alfard_input,
)

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

CHECKPOINT_PATH = ALFARD_HOME / ".setup_checkpoint.yaml"


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


def _load_checkpoint(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _save_checkpoint(path: Path, data: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def run_setup() -> None:
    ALFARD_HOME.mkdir(parents=True, exist_ok=True)
    (ALFARD_HOME / "config").mkdir(exist_ok=True)
    (ALFARD_HOME / "logs").mkdir(exist_ok=True)

    # ── CHECKPOINT CHECK ──────────────────────────────────────────────────────
    saved = _load_checkpoint(CHECKPOINT_PATH)
    ck: dict = {}

    if saved:
        steps_done_so_far = saved.get("steps_done", [])
        steps_str = ", ".join(steps_done_so_far) if steps_done_so_far else "none"
        console.print(
            f"\n{c('fg_dim', 'setup was started before.')}"
            f"\n{c('fg_dim', f'completed: {steps_str}')}\n"
        )
        choice = alfard_select(
            "resume or start over?",
            ["resume", "start over"],
            default="resume",
        )
        if choice == "start over":
            CHECKPOINT_PATH.unlink(missing_ok=True)
        else:
            ck = saved

    steps_done: list[str] = ck.get("steps_done", [])

    # ── 1. WELCOME ────────────────────────────────────────────────────────────
    console.print()
    console.print(header_block("0.1.0"))
    console.print()
    console.print(f"[{p.fg_dim}]secure by default. every action logged. your data stays on your machine.[/]")
    console.print(f"[{p.fg_dim}]this wizard sets up alfard in about 2 minutes.[/]")
    console.print()

    # Dependency check
    from alfard.setup.dependencies import ensure_dependencies
    if not ensure_dependencies():
        console.print(error_block(
            agent="alfard setup",
            state="failed",
            headline="setup cannot continue — missing required dependencies.",
            explanation="install node.js from nodejs.org and re-run alfard setup.",
        ))
        return

    # ── 3. LLM PROVIDER ───────────────────────────────────────────────────────
    provider: str
    model: str
    base_url: str
    api_key_env: str | None = None

    if "provider" in steps_done:
        config_path = ALFARD_HOME / "config" / "alfard.yaml"
        with config_path.open() as f:
            saved_cfg = yaml.safe_load(f)
        provider = saved_cfg["provider"]["name"]
        model = saved_cfg["provider"]["model"]
        base_url = saved_cfg["provider"]["base_url"]
        api_key_env = saved_cfg["provider"].get("api_key_env")
        console.print(
            f"\n{c('fg_dim', f'provider already configured: {provider} / {model} — skipping.')}"
        )
    else:
        console.print(f"\n[{p.fg_em}]llm provider[/]")
        console.print(f"[{p.fg_dim}]which provider do you want to use?[/]\n")

        provider_names = list(PROVIDERS.values())
        for name in provider_names:
            tag = f"  {c('fg_faint', '(local, no key needed)')}" if name in LOCAL_PROVIDERS else ""
            default_marker = f"  {c('fg_faint', '(default)')}" if name == "openrouter" else ""
            console.print(f"  {c('fg_em', name)}{tag}{default_marker}")
        console.print()

        raw_provider = alfard_select("provider", provider_names, default="openrouter")
        provider = raw_provider or "openrouter"

        base_url = PROVIDER_BASE_URLS[provider]

        if provider in CLOUD_PROVIDERS:
            api_key_env = PROVIDER_API_KEY_ENV[provider]
            api_key = alfard_input(f"{provider} api key", password=True)
            _update_env_file(ALFARD_HOME / ".env", api_key_env, api_key)
        else:
            console.print(f"\n[{p.fg_dim}]default url: {base_url}[/]")
            base_url = alfard_input("base url", default=base_url).rstrip("/") or base_url

        model_names = [name for _, name in PROVIDER_MODELS[provider]]
        console.print(f"\n[{p.fg_dim}]select a model:[/]")
        raw_model = alfard_select("model", model_names, default=model_names[0])
        model = raw_model or model_names[0]

        if model == "custom":
            model = alfard_input("custom model name") or model_names[0]

        config_dir = ALFARD_HOME / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
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
            f"\n{dot('ok')} [{p.fg_dim}]provider configured: {provider} / {model}[/]"
        )
        console.print(f"\n[{p.fg_dim}]memory — alfard uses a lightweight embedding model to give your agent[/]")
        console.print(f"[{p.fg_dim}]persistent memory across conversations. cost: < $0.001/day.[/]")

        steps_done = list(dict.fromkeys(steps_done + ["provider"]))
        _save_checkpoint(CHECKPOINT_PATH, {
            "steps_done": steps_done,
            "provider": provider,
            "agent_name": ck.get("agent_name", ""),
        })

    # ── 4. CREATE FIRST AGENT ─────────────────────────────────────────────────
    from alfard.agents.loader import AGENTS_DIR

    agent_name: str

    if "agent_created" in steps_done:
        agent_name = ck.get("agent_name", "")
        console.print(
            f"\n{c('fg_dim', f'agent already created: {agent_name} — skipping.')}"
        )
    else:
        console.print(f"\n[{p.fg_em}]create your first agent[/]")
        console.print(f"[{p.fg_dim}]agents are ai assistants with their own identity and skills.[/]\n")
        console.print(f"[{p.fg_dim}]your answers define this agent's permanent identity.[/]")
        console.print(f"[{p.fg_dim}]they become soul.md — the document that shapes every response.[/]")

        agent_name = ""

        while True:
            while True:
                agent_name = alfard_input(
                    "agent name",
                    hint="lowercase, hyphens ok, e.g. my-agent   ·   leave blank to exit setup",
                ).strip().lower()
                if not agent_name:
                    return
                if not re.match(r'^[a-z0-9-]+$', agent_name):
                    console.print(
                        f"  [{p.err}]name must be lowercase letters, numbers, and hyphens only.[/]"
                    )
                    continue
                break

            agent_dir = AGENTS_DIR / agent_name
            if agent_dir.exists():
                console.print(
                    f"  [{p.warn}]agent '{agent_name}' already exists — using existing agent.[/]"
                )
                break

            console.print()
            description = alfard_input(
                "what does this agent do?",
                hint="e.g. triages my gmail inbox, flags urgent messages, drafts replies",
            ).strip()

            personality = alfard_input(
                "personality or tone",
                hint="e.g. concise, direct, never uses bullet points",
                default="helpful and concise",
            ).strip()

            console.print(f"\n[{p.fg_faint}]soul preview[/]")
            console.print(f"[{p.fg_dim}]name:    [/][{p.fg_em}]{agent_name}[/]")
            console.print(f"[{p.fg_dim}]purpose: [/][{p.fg_em}]{description}[/]")
            console.print(f"[{p.fg_dim}]tone:    [/][{p.fg_em}]{personality}[/]")
            console.print(f"[{p.fg_faint}]edit later with: alfard edit {agent_name} soul[/]\n")

            if alfard_confirm("looks good?", default=True):
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
                (agent_dir / "brain.md").write_text(
                    f"# {agent_name} — knowledge\n\n", encoding="utf-8"
                )
                (agent_dir / "memory.md").write_text(
                    f"# {agent_name} — memory\n\n", encoding="utf-8"
                )
                console.print(
                    f"{dot('ok')} [{p.fg_dim}]alfard created {agent_name}.[/]"
                )
                break
            # loop back — re-ask name, purpose, and tone

        steps_done = list(dict.fromkeys(steps_done + ["agent_created"]))
        _save_checkpoint(CHECKPOINT_PATH, {
            "steps_done": steps_done,
            "provider": provider,
            "agent_name": agent_name,
        })

    # ── 5. SKILLS ─────────────────────────────────────────────────────────────
    if "skills" not in steps_done:
        console.print(f"\n[{p.fg_em}]skills[/]")
        console.print(
            f"[{p.fg_dim}]skills give your agent new capabilities — web search, memory tools, custom actions.[/]\n"
        )

        from alfard.agents.loader import list_available_skills, add_skill

        available = list_available_skills()
        if not available:
            console.print(
                f"[{p.fg_faint}]no skills in the library yet. add skills later:\n"
                f"  alfard skill add {agent_name}[/]"
            )
        else:
            selected = alfard_multiselect(
                "add skills from the library:",
                available,
            )
            if selected:
                for s in selected:
                    add_skill(agent_name, s)
                console.print(
                    f"{dot('ok')} [{p.fg_dim}]skills added.[/]"
                )

        steps_done = list(dict.fromkeys(steps_done + ["skills"]))
        _save_checkpoint(CHECKPOINT_PATH, {
            "steps_done": steps_done,
            "provider": provider,
            "agent_name": agent_name,
        })

    # ── 6. CONNECT INTEGRATION (optional) ─────────────────────────────────────
    connected_integration: bool = ck.get("connected_integration", False)
    has_gmail = False

    if "integrations" not in steps_done:
        try:
            from alfard.integrations.catalogue import CATALOGUE as _CAT
            _gmail_available = "gmail" in _CAT
        except Exception:
            _gmail_available = False

        if _gmail_available:
            google_client_id = os.environ.get("ALFARD_GOOGLE_CLIENT_ID", "")
            if google_client_id and google_client_id != "custom":
                console.print(
                    f"{dot('ok')} [{p.fg_dim}]google credentials are bundled — oauth is automatic.[/]"
                )
            else:
                console.print(
                    f"[{p.fg_dim}]gmail requires a one-time google cloud project setup (~5 min).[/]"
                )

        console.print(f"\n[{p.fg_em}]connect an integration[/] [{p.fg_faint}](optional)[/]")
        console.print(f"[{p.fg_dim}]connect notion, gmail, github, slack and more.[/]\n")

        from alfard.integrations.catalogue import CATALOGUE, AUTH_APIKEY
        from alfard.cli.cmd_connect import _connect_apikey, _connect_oauth, _load_integrations
        from alfard.cli.ui_helpers import render_integration_table

        _int_data = _load_integrations()
        _connected_set = {s["name"] for s in _int_data.get("servers", [])}
        console.print(render_integration_table(CATALOGUE, _connected_set))
        console.print(
            f"  [{p.fg_faint}]leave empty to skip — connect later with alfard connect[/]\n"
        )

        _names = list(CATALOGUE.keys())
        _selected = alfard_multiselect(
            "which integrations would you like to connect?",
            _names,
        )

        if _selected:
            for chosen in _selected:
                info = CATALOGUE[chosen]
                if info["auth"] == AUTH_APIKEY:
                    _connect_apikey(chosen, info)
                else:
                    _connect_oauth(chosen, info)
                connected_integration = True
                if chosen == "gmail":
                    has_gmail = True
        else:
            console.print(
                f"[{p.fg_faint}]connect integrations later: alfard connect[/]"
            )

        steps_done = list(dict.fromkeys(steps_done + ["integrations"]))
        _save_checkpoint(CHECKPOINT_PATH, {
            "steps_done": steps_done,
            "provider": provider,
            "agent_name": agent_name,
            "connected_integration": connected_integration,
        })

    # ── 7. DONE ───────────────────────────────────────────────────────────────
    has_cron = False

    console.print(f"\n{dot('ok')} [{p.fg_dim}]alfard is ready.[/]\n")
    console.print(f"[{p.fg_dim}]your agent: [/][{p.fg_em}]{agent_name}[/]\n")
    console.print(f"[{p.fg_dim}]what to do next:[/]")
    console.print(f"  [{p.fg_em}]alfard run {agent_name}[/]")
    if not connected_integration:
        console.print(f"  [{p.fg_dim}]alfard connect[/]       [{p.fg_faint}]connect integrations[/]")
    elif not has_cron:
        console.print(f"  [{p.fg_dim}]alfard cron add[/]     [{p.fg_faint}]schedule recurring tasks[/]")
    console.print(f"  [{p.fg_dim}]alfard --help[/]         [{p.fg_faint}]see all commands[/]")

    venv_bin = Path(sys.executable).parent
    export_line_sh   = f'export PATH="{venv_bin}:$PATH"'
    export_line_fish = f'set -gx PATH "{venv_bin}" $PATH'

    console.print(f"\n[{p.fg_em}]one more step — shell access[/]")
    console.print(f"[{p.fg_dim}]add this to your shell config so alfard works from anywhere:[/]\n")
    console.print(f"  [{p.fg_em}]zsh / bash[/]")
    console.print(f"  [{p.fg_faint}]  {export_line_sh}[/]")
    console.print(f"\n  [{p.fg_em}]fish[/]")
    console.print(f"  [{p.fg_faint}]  {export_line_fish}[/]")
    console.print(f"\n[{p.fg_dim}]then restart your terminal or run:[/]")
    console.print(f"  [{p.fg_faint}]source ~/.zshrc[/]   [{p.fg_dim}](zsh)[/]")
    console.print(f"  [{p.fg_faint}]source ~/.bash_profile[/]   [{p.fg_dim}](bash)[/]")

    CHECKPOINT_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    run_setup()
