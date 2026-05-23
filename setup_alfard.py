"""Interactive first-run setup — gets alfard working from scratch."""

import os
import re
import sys
import time
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

STEP_LABELS = {
    2: "create your agent",
    3: "add skills",
    4: "connect integrations",
    5: "schedule tasks",
    6: "mount folders",
}


def _section_transition(summary: str, next_step: int) -> None:
    """Print summary, pause, clear, reprint banner and progress indicator."""
    console.print(f"\n{dot('ok')} [{p.fg_dim}]{summary}[/]")
    time.sleep(0.6)
    console.clear()
    console.print()
    console.print(header_block("0.1.0"))
    console.print()
    label = STEP_LABELS.get(next_step, "")
    console.print(f"[{p.fg_dim}]step {next_step} of 6 — {label}[/]\n")


_WEB_ACCESS_CATALOGUE_ENTRY: dict = {
    "description": "web search and page fetch for your agent",
    "display_auth": "api key (optional)",
}


def _setup_connect_web_access(agent_name: str) -> None:
    """Provider selection + config save for web access during setup."""
    from alfard.agents.loader import AGENTS_DIR, add_skill
    from alfard.web.config import WebConfig

    import questionary as _q

    console.print(f"\n[{p.fg_em}]web access[/]")
    raw = alfard_select(
        "search provider",
        [
            _q.Choice("duckduckgo  — no key needed", value="duckduckgo"),
            _q.Choice("brave search  — api key required", value="brave search"),
            _q.Choice("searxng  — self-hosted url required", value="searxng"),
        ],
        default="duckduckgo",
    ) or "duckduckgo"

    cfg = WebConfig(AGENTS_DIR / agent_name)

    if raw == "brave search":
        key = alfard_input("brave search api key", password=True).strip()
        cfg.update(enabled=True, search_provider="brave", brave_api_key=key or None)
    elif raw == "searxng":
        url = alfard_input("searxng base url", default="http://localhost:8080").strip()
        cfg.update(enabled=True, search_provider="searxng", searxng_url=url or None)
    else:
        cfg.update(enabled=True, search_provider="duckduckgo")

    cfg.save()
    add_skill(agent_name, "web_usage")
    console.print(f"\n{dot('ok')} [{p.fg_dim}]web access connected: {raw}[/]")



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
        raw_provider = alfard_select("provider", provider_names, default="openrouter")
        provider = raw_provider or "openrouter"

        base_url = PROVIDER_BASE_URLS[provider]

        if provider in CLOUD_PROVIDERS:
            api_key_env = PROVIDER_API_KEY_ENV[provider]
            while True:
                api_key = alfard_input(f"{provider} api key", password=True)
                if api_key.strip():
                    break
                console.print(f"  [{p.warn}]key looks empty — continue anyway? (y/n)[/] ", end="")
                answer = input().strip().lower()
                if answer == "n":
                    continue
                break
            collected_keys = {api_key_env: api_key}
        else:
            console.print(f"\n[{p.fg_dim}]default url: {base_url}[/]")
            base_url = alfard_input("base url", default=base_url).rstrip("/") or base_url

        model_names = [name for _, name in PROVIDER_MODELS[provider]]
        console.print(f"\n[{p.fg_dim}]select a model:[/]")
        raw_model = alfard_select("model", model_names, default=model_names[0])
        model = raw_model or model_names[0]

        if model == "custom":
            custom_input = alfard_input("custom model name")
            if not custom_input.strip():
                console.print(f"  [{p.fg_dim}]no input — defaulting to {model_names[0]}[/]")
                model = model_names[0]
            else:
                model = custom_input

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

        if provider in CLOUD_PROVIDERS:
            from alfard.security.keystore import write_env_encrypted, using_keyring
            write_env_encrypted(ALFARD_HOME, collected_keys)
            backend = "(OS keyring)" if using_keyring(ALFARD_HOME) else "(key file — keyring unavailable)"
            console.print(f"\n{dot('ok')} [{p.fg_dim}]API keys encrypted and stored {backend}[/]")

        steps_done = list(dict.fromkeys(steps_done + ["provider"]))
        _save_checkpoint(CHECKPOINT_PATH, {
            "steps_done": steps_done,
            "provider": provider,
            "agent_name": ck.get("agent_name", ""),
        })
        _section_transition(f"provider configured: {provider} / {model}", next_step=2)

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
            console.print(f"[{p.fg_dim}]describe what this agent does — be as specific as possible.[/]")
            console.print(f"[{p.fg_dim}]a couple of sentences is ideal. this becomes the core of soul.md[/]")
            console.print(f"[{p.fg_dim}]and will define the agent's purpose in every conversation.[/]\n")
            description = alfard_input(
                "what does this agent do?",
                hint="e.g. triages my gmail inbox, flags urgent emails by sender and topic, drafts replies in my voice",
            ).strip()

            personality = alfard_input(
                "personality or tone",
                hint="e.g. concise, direct, never uses bullet points",
            ).strip() or "helpful and concise"

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
                break
            # loop back — re-ask name, purpose, and tone

        steps_done = list(dict.fromkeys(steps_done + ["agent_created"]))
        _save_checkpoint(CHECKPOINT_PATH, {
            "steps_done": steps_done,
            "provider": provider,
            "agent_name": agent_name,
        })
        _section_transition(f"agent created: {agent_name}", next_step=3)

    # ── 5. SKILLS ─────────────────────────────────────────────────────────────
    if "skills" not in steps_done:
        console.print(f"\n[{p.fg_em}]skills[/]")
        from alfard.agents.loader import add_skill, SKILLS_DIR

        console.print(
            f"{dot('ok')} [{p.fg_dim}]Essential skills included: memory, tasks, projects, research, reasoning, communication, debugging[/]"
        )
        console.print(
            f"  [{p.fg_faint}]Add more: alfard skill add {agent_name}[/]\n"
        )

        if alfard_confirm("create a custom skill?", default=False):
            while True:
                skill_name = alfard_input(
                    "skill name",
                    hint="lowercase, hyphens ok   ·   leave blank to skip",
                ).strip().lower()
                if not skill_name:
                    break
                if not re.match(r'^[a-z0-9-]+$', skill_name):
                    console.print(f"  [{p.err}]lowercase letters, numbers, and hyphens only.[/]")
                    continue
                dest = SKILLS_DIR / f"{skill_name}.md"
                if dest.exists():
                    console.print(f"  [{p.warn}]'{skill_name}' already exists — skipping.[/]")
                    break
                skill_desc = alfard_input("one-line description:").strip()
                SKILLS_DIR.mkdir(exist_ok=True)
                dest.write_text(
                    f"# {skill_name.capitalize()} skill\n\n"
                    f"{skill_desc}\n\n"
                    f"## How it works\n\n\n"
                    f"## Rules\n\n\n"
                    f"## Common mistakes to avoid\n\n",
                    encoding="utf-8",
                )
                add_skill(agent_name, skill_name)
                console.print(
                    f"{dot('ok')} [{p.fg_dim}]skill '{skill_name}' created and added to {agent_name}.[/]"
                )
                console.print(
                    f"  [{p.fg_faint}]edit it later: alfard skill edit {skill_name}[/]"
                )
                break

        steps_done = list(dict.fromkeys(steps_done + ["skills"]))
        _save_checkpoint(CHECKPOINT_PATH, {
            "steps_done": steps_done,
            "provider": provider,
            "agent_name": agent_name,
        })
        _section_transition("skills configured", next_step=4)

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

        console.print(f"\n[{p.fg_em}]connect an integration[/] [{p.fg_faint}](optional)[/]")
        console.print(f"[{p.fg_dim}]connect notion, gmail, github, slack and more.[/]\n")

        import questionary as _q
        from alfard.integrations.catalogue import CATALOGUE, AUTH_APIKEY
        from alfard.cli.cmd_connect import _connect_apikey, _connect_oauth, _load_integrations

        _extended_catalogue = {**CATALOGUE, "web access": _WEB_ACCESS_CATALOGUE_ENTRY}

        _int_data = _load_integrations()
        _connected_set = {s["name"] for s in _int_data.get("servers", [])}
        console.print(
            f"  [{p.fg_faint}]leave empty to skip — connect later with alfard connect[/]\n"
        )

        def _int_auth_label(info: dict) -> str:
            if info.get("display_auth"):
                return info["display_auth"]
            return "api key" if info.get("auth") == AUTH_APIKEY else "oauth"

        _int_choices = [
            _q.Choice(
                title=f"{name}  ({_int_auth_label(info)})" + ("  ● connected" if name in _connected_set else ""),
                value=name,
            )
            for name, info in _extended_catalogue.items()
        ]
        _selected = alfard_multiselect(
            "which integrations would you like to connect?",
            _int_choices,
        )

        if _selected:
            for chosen in _selected:
                if chosen == "web access":
                    _setup_connect_web_access(agent_name)
                    connected_integration = True
                    continue
                info = CATALOGUE[chosen]
                if info["auth"] == AUTH_APIKEY:
                    _connect_apikey(chosen, info)
                else:
                    if chosen == "gmail":
                        gid = os.environ.get("ALFARD_GOOGLE_CLIENT_ID", "")
                        if not gid or gid == "custom":
                            console.print(
                                f"[{p.fg_dim}]gmail requires a one-time google cloud project setup (~5 min).[/]"
                            )
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
        _section_transition("integrations configured", next_step=5)

    # ── 7. SCHEDULE TASKS (optional) ─────────────────────────────────────────
    if "cron" not in steps_done:
        console.print(f"\n[{p.fg_em}]schedule a task[/] [{p.fg_faint}](optional)[/]")
        console.print(
            f"[{p.fg_dim}]schedule a recurring task? set up cron jobs now or"
            f" later with: alfard cron add[/]\n"
        )

        if alfard_confirm("set up a cron job now?", default=False):
            from alfard.cli.cmd_cron import _collect_schedule, _load_crons, _save_crons, _slug
            from alfard.agents.loader import AgentLoader

            job_name_raw = alfard_input(
                "job name",
                hint="e.g. morning inbox summary",
            ).strip()
            if job_name_raw:
                job_slug = _slug(job_name_raw)
                task = alfard_input(
                    "describe the task in detail",
                    hint="what to fetch, what to do with it, and what the output should be",
                ).strip()
                if task:
                    loader = AgentLoader(agent_name)
                    available_skills = loader.get_agent_skills()
                    linked_skills: list[str] = []
                    if available_skills:
                        linked_skills = alfard_multiselect(
                            "which skills should this job use? (optional — space to toggle, enter to confirm)",
                            available_skills,
                        )
                    cron_expr = _collect_schedule()
                    if cron_expr:
                        jobs = _load_crons(agent_name)
                        jobs.append({
                            "name": job_slug,
                            "task": task,
                            "schedule": cron_expr,
                            "linked_skills": linked_skills,
                            "enabled": True,
                        })
                        _save_crons(agent_name, jobs)
                        console.print(f"\n{dot('ok')} [{p.fg_dim}]job added.[/]")
                        console.print(f"[{p.fg_faint}]start scheduler: alfard cron run[/]")
        else:
            console.print(f"[{p.fg_faint}]add cron jobs later: alfard cron add[/]")

        steps_done = list(dict.fromkeys(steps_done + ["cron"]))
        _save_checkpoint(CHECKPOINT_PATH, {
            "steps_done": steps_done,
            "provider": provider,
            "agent_name": agent_name,
            "connected_integration": connected_integration,
        })
        _section_transition("schedule configured", next_step=6)

    # ── 8. MOUNT FOLDERS (optional) ──────────────────────────────────────────
    if "mounts" not in steps_done:
        console.print(f"\n[{p.fg_em}]mount a folder[/] [{p.fg_faint}](optional)[/]")
        console.print(
            f"[{p.fg_dim}]mount a local folder so your agent can read files?[/]\n"
        )

        if alfard_confirm("mount a folder now?", default=False):
            from alfard.cli.cmd_mount import _load_mounts, _save_mounts

            folder_path = alfard_input(
                "folder path",
                hint="e.g. ~/Documents/work",
            ).strip()
            if folder_path:
                resolved = Path(folder_path).expanduser().resolve()
                if not resolved.exists() or not resolved.is_dir():
                    console.print(f"  [{p.warn}]path not found or not a directory — skipping.[/]")
                    console.print(f"[{p.fg_faint}]mount folders later: alfard mount add[/]")
                else:
                    access = alfard_select(
                        "access level?",
                        ["readonly", "readwrite"],
                        default="readonly",
                    ) or "readonly"
                    data = _load_mounts(agent_name)
                    stored_path = str(Path(folder_path).expanduser())
                    existing_paths = [m["path"] for m in data.get("mounts", [])]
                    if stored_path in existing_paths:
                        console.print(f"  [{p.warn}]already mounted: {folder_path}[/]")
                    else:
                        data.setdefault("mounts", []).append({
                            "path": stored_path,
                            "access": access,
                        })
                        _save_mounts(agent_name, data)
                        access_label = "read+write" if access == "readwrite" else "read only"
                        console.print(f"\n{dot('ok')} [{p.fg_dim}]folder mounted.[/]")
                        console.print(f"  [{p.fg_faint}]{'path':<8}[/] [{p.fg_em}]{resolved}[/]")
                        console.print(f"  [{p.fg_faint}]{'access':<8}[/] [{p.fg_dim}]{access_label}[/]")
        else:
            console.print(f"[{p.fg_faint}]mount folders later: alfard mount add[/]")

        steps_done = list(dict.fromkeys(steps_done + ["mounts"]))
        _save_checkpoint(CHECKPOINT_PATH, {
            "steps_done": steps_done,
            "provider": provider,
            "agent_name": agent_name,
            "connected_integration": connected_integration,
        })

    # ── 9. DONE ───────────────────────────────────────────────────────────────
    CHECKPOINT_PATH.unlink(missing_ok=True)
    console.clear()
    console.print()
    console.print(header_block("0.1.0"))
    console.print()
    console.print(f"{dot('ok')} [{p.fg_em}]alfard is ready.[/]\n")
    console.print(f"[{p.fg_dim}]before you start — a few things worth knowing:[/]\n")
    console.print(f"[{p.fg_em}]memory[/]      [{p.fg_dim}]your agent remembers facts, preferences and[/]")
    console.print(f"            [{p.fg_dim}]mistakes across every session. stored locally[/]")
    console.print(f"            [{p.fg_dim}]in ~/.alfard/ — never sent anywhere.[/]\n")
    console.print(f"[{p.fg_em}]security[/]    [{p.fg_dim}]every action is logged. irreversible actions[/]")
    console.print(f"            [{p.fg_dim}](sending emails, deleting files) require your[/]")
    console.print(f"            [{p.fg_dim}]explicit approval before they run.[/]\n")
    console.print(f"[{p.fg_dim}]your data stays on your machine. always.[/]")
    console.print(f"\n[{p.fg_faint}]press enter to open alfard →[/] ", end="")
    input()

    from alfard.cli.main import cli
    cli.main([], standalone_mode=False)


def run_provider_settings() -> None:
    """Interactive flow to change provider, model, or API key without re-running full setup."""
    config_path = ALFARD_HOME / "config" / "alfard.yaml"
    if not config_path.exists():
        console.print(f"\n  [{p.err}]no config found — run alfard setup first.[/]")
        return

    with config_path.open() as f:
        cfg = yaml.safe_load(f)

    current_provider = cfg["provider"]["name"]
    current_model = cfg["provider"]["model"]
    current_base_url = cfg["provider"].get("base_url", PROVIDER_BASE_URLS.get(current_provider, ""))

    console.print(f"\n[{p.fg_faint}]current[/]")
    console.print(f"  [{p.fg_dim}]provider  [/][{p.fg_em}]{current_provider}[/]")
    console.print(f"  [{p.fg_dim}]model     [/][{p.fg_em}]{current_model}[/]")
    if current_provider in CLOUD_PROVIDERS:
        console.print(f"  [{p.fg_dim}]api key   [/][{p.fg_faint}]•••• (encrypted)[/]")
    else:
        console.print(f"  [{p.fg_dim}]base url  [/][{p.fg_em}]{current_base_url}[/]")
    console.print()

    if current_provider in CLOUD_PROVIDERS:
        options = ["change provider & model", "change model", "change api key", "← back"]
    else:
        options = ["change provider & model", "change model", "change base url", "← back"]

    action = alfard_select("what would you like to change?", options)
    if not action or action == "← back":
        return

    if action == "change provider & model":
        provider_names = list(PROVIDERS.values())
        new_provider = alfard_select("provider", provider_names, default=current_provider) or current_provider
        base_url = PROVIDER_BASE_URLS[new_provider]
        api_key_env = None

        if new_provider in CLOUD_PROVIDERS:
            api_key_env = PROVIDER_API_KEY_ENV[new_provider]
            while True:
                api_key = alfard_input(f"{new_provider} api key", password=True)
                if api_key.strip():
                    break
                console.print(f"  [{p.warn}]key looks empty — continue anyway? (y/n)[/] ", end="")
                if input().strip().lower() != "n":
                    break
            from alfard.security.keystore import write_env_encrypted, using_keyring
            write_env_encrypted(ALFARD_HOME, {api_key_env: api_key})
            backend = "(OS keyring)" if using_keyring(ALFARD_HOME) else "(key file)"
            console.print(f"\n{dot('ok')} [{p.fg_dim}]api key encrypted and stored {backend}[/]")
        else:
            console.print(f"\n[{p.fg_dim}]default url: {base_url}[/]")
            base_url = alfard_input("base url", default=base_url).rstrip("/") or base_url

        model_names = [name for _, name in PROVIDER_MODELS[new_provider]]
        raw_model = alfard_select("model", model_names, default=model_names[0]) or model_names[0]
        new_model = raw_model
        if new_model == "custom":
            custom_input = alfard_input("custom model name").strip()
            new_model = custom_input if custom_input else model_names[0]

        cfg["provider"] = {
            "name": new_provider,
            "model": new_model,
            "base_url": base_url,
            "api_key_env": api_key_env,
        }
        with config_path.open("w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
        console.print(f"\n{dot('ok')} [{p.fg_dim}]provider updated: {new_provider} / {new_model}[/]")

    elif action == "change model":
        model_names = [name for _, name in PROVIDER_MODELS.get(current_provider, [("1", "custom")])]
        default_model = current_model if current_model in model_names else model_names[0]
        raw_model = alfard_select("model", model_names, default=default_model) or current_model
        new_model = raw_model
        if new_model == "custom":
            custom_input = alfard_input("custom model name").strip()
            new_model = custom_input if custom_input else current_model
        cfg["provider"]["model"] = new_model
        with config_path.open("w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
        console.print(f"\n{dot('ok')} [{p.fg_dim}]model updated: {new_model}[/]")

    elif action == "change api key":
        api_key_env = PROVIDER_API_KEY_ENV[current_provider]
        while True:
            api_key = alfard_input(f"{current_provider} api key", password=True)
            if api_key.strip():
                break
            console.print(f"  [{p.warn}]key looks empty — continue anyway? (y/n)[/] ", end="")
            if input().strip().lower() != "n":
                break
        from alfard.security.keystore import write_env_encrypted, using_keyring
        write_env_encrypted(ALFARD_HOME, {api_key_env: api_key})
        backend = "(OS keyring)" if using_keyring(ALFARD_HOME) else "(key file)"
        console.print(f"\n{dot('ok')} [{p.fg_dim}]api key updated {backend}[/]")

    elif action == "change base url":
        console.print(f"\n[{p.fg_dim}]current url: {current_base_url}[/]")
        new_base_url = alfard_input("base url", default=current_base_url).rstrip("/") or current_base_url
        cfg["provider"]["base_url"] = new_base_url
        with config_path.open("w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
        console.print(f"\n{dot('ok')} [{p.fg_dim}]base url updated: {new_base_url}[/]")


if __name__ == "__main__":
    run_setup()
