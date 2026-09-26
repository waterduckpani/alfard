<p align="center">
  <img src="https://raw.githubusercontent.com/waterduckpani/alfard/master/.github/readme/banner.png" alt="Alfard: a local AI agent runtime that never acts without you" width="100%">
</p>

<div align="center">

[![pypi](https://img.shields.io/pypi/v/alfard?style=flat-square&label=pypi&color=1f2328)](https://pypi.org/project/alfard/)
[![npm](https://img.shields.io/npm/v/alfard-cli?style=flat-square&label=npm&color=1f2328)](https://www.npmjs.com/package/alfard-cli)
![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-1f2328?style=flat-square)
![platform: macOS | Linux | Windows](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-1f2328?style=flat-square)
[![license: MIT](https://img.shields.io/badge/license-MIT-1f2328?style=flat-square)](https://github.com/waterduckpani/alfard/blob/master/LICENSE)

**A local AI agent runtime. You own it, you control it, and it never acts without you.**<br>
<sub>CLI · Python · PyPI + npm</sub>

[Overview](#overview) · [Highlights](#highlights) · [Screenshots](#screenshots) · [How it works](#how-it-works) · [Getting started](#getting-started) · [Status](#status-and-roadmap)

</div>

<p align="center">
  <img src="https://raw.githubusercontent.com/waterduckpani/alfard/master/assets/approvalgate.gif" width="480" alt="Alfard approval gate demo">
  <br>
  <sub>The approval gate stops an irreversible action until you answer y or n.</sub>
</p>

> [!NOTE]
> Full documentation is coming soon. Until then, everything you need is in this README.

## Overview

Alfard runs AI agents on your own machine. Each agent has its own persistent memory, connects to your real tools (Gmail, Notion, GitHub, Slack, Linear) and talks to you from the terminal, Telegram, Discord or Slack at the same time.

Before anything irreversible happens, it stops and asks you. Your answer is logged, nothing runs silently, and nothing leaves your machine.

## Highlights

| Feature | What it does |
|---|---|
| **Approval gate** | Halts before every irreversible action and shows the tool, arguments and source. Logged either way, and it cannot be bypassed. |
| **Typed persistent memory** | Ten memory categories scored by relevance, recency and importance. A reflect cycle proposes improvements you approve one by one. |
| **Every channel at once** | Terminal, Telegram, Discord and Slack share one agent and one memory. The approval prompt adapts to each channel. |
| **Encrypted credentials** | API keys are Fernet-encrypted at rest, with the key held in your OS keychain. |
| **Prompt-injection defence** | A sanitiser, a behavioural gate and a strip safety net keep web content from steering the agent. |
| **Any model** | OpenRouter, OpenAI, Anthropic, or fully local through Ollama and LM Studio. |

<details>
<summary><strong>Everything else it does</strong></summary>

| Feature | What it does |
|---|---|
| **Full audit trail** | Every LLM call, tool execution, gate decision and session event logged to `audit.jsonl` with UTC timestamps. |
| **Service mode** | Install an agent as a background service: it runs 24/7 on every connected channel, starts on boot and recovers from crashes. No elevation required. |
| **Cron jobs** | Schedule any agent task on a timer, with a full cron UI in `alfard cron`. |
| **Slash commands** | `/new` `/remember` `/status` `/skills` `/reset` `/model` `/help`, in every channel. |
| **Skills system** | Markdown-defined, per-agent and composable. Seven built in; add your own in `~/.alfard/skills/`. |
| **Interactive menu** | `alfard` opens an arrow-key menu for agents, channels, integrations, skills, memory and settings. |

</details>

## Screenshots

<p align="center">
  <img src="https://raw.githubusercontent.com/waterduckpani/alfard/master/.github/readme/showcase.png" width="100%" alt="The approval gate, memory notifications in Discord, and the main menu">
</p>

## How it works

Every tool call passes through the same path, whichever channel the request came from.

```text
 Channels: terminal · Telegram · Discord · Slack
     │
     ▼
 Agent ── soul.md · skills · brain.db (typed memory)
     │  tool call
     ▼
 Tool registry ── classifies every tool as reversible or irreversible
     │
     ├── reversible ─────────────────────────────┐
     │                                           │
     └── irreversible ──▶ Approval gate: y / n ──┤
                                                 │ approved
     ┌───────────────────────────────────────────┘
     ▼
 Sandbox executor ── own OS process, 30 s timeout
     │
     ▼
 audit.jsonl ── every call, decision and event, in UTC
```

- **Unregistered tools cannot run.** The registry is built at startup, so an unclassified call is structurally impossible.
- **File work happens on a disposable git branch**, leaving your working tree untouched.
- **No telemetry.** Nothing phones home.

<details>
<summary><strong>Memory</strong></summary>

Every agent has a persistent `brain.db` that survives across sessions, typed into ten categories:

`fact` · `preference` · `goal` · `project_state` · `procedure` · `mistake` · `tool_pattern` · `decision` · `person` · `constraint`

Each memory has a confidence score, importance weight and valence. Retrieval blends relevance, recency and importance, and `project_state` always surfaces first.

**Reflect** fires every 20 messages, every 30 minutes idle and every 10 sessions, and proposes improvements based on patterns it finds. You approve or reject each proposal before it writes, and rejected proposals never come back. After every confirmed write, the active channel shows exactly what was remembered and as what type.

</details>

<details>
<summary><strong>Security model</strong></summary>

Security is the architecture, not a feature layer. The full model is in [SECURITY.md](https://github.com/waterduckpani/alfard/blob/master/SECURITY.md).

- **Approval gate** on every irreversible action, on every channel, with no bypass
- **Encrypted credentials**: Fernet plus the OS keychain, with automatic migration from plaintext on upgrade
- **Three-layer prompt-injection protection**: sanitiser, behavioural gate and strip safety net. Sanitised content is source-attributed before it enters the LLM context
- **Sandbox executor**: every tool call runs in an isolated OS subprocess with a hard 30-second timeout
- **Tool registry and classifier**: every tool is registered as reversible or irreversible at startup
- **Worktree isolation**: agent file operations go to a disposable git branch
- **Memory secret blocking**: API keys, tokens and passwords are blocked before any `brain.db` write
- **Channel allowlists**: Telegram and Discord require explicit user and guild allowlists
- **No telemetry**

To report a vulnerability, see [SECURITY.md](https://github.com/waterduckpani/alfard/blob/master/SECURITY.md#responsible-disclosure). Please do not open a public issue.

</details>

## Tech stack

| Layer | Tools |
|---|---|
| **Language & CLI** | ![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white) ![Click](https://img.shields.io/badge/Click-1f2328?style=flat-square) ![Rich](https://img.shields.io/badge/Rich-1f2328?style=flat-square) ![questionary](https://img.shields.io/badge/questionary-1f2328?style=flat-square) |
| **Runtime** | ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white) ![APScheduler](https://img.shields.io/badge/APScheduler-1f2328?style=flat-square) ![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white) ![MCP](https://img.shields.io/badge/MCP-1f2328?style=flat-square) |
| **Models** | ![Anthropic](https://img.shields.io/badge/Anthropic-191919?style=flat-square&logo=anthropic&logoColor=white) ![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat-square&logo=openai&logoColor=white) ![OpenRouter](https://img.shields.io/badge/OpenRouter-6467F2?style=flat-square) ![Ollama](https://img.shields.io/badge/Ollama-000000?style=flat-square&logo=ollama&logoColor=white) |
| **Channels** | ![Telegram](https://img.shields.io/badge/Telegram-26A5E4?style=flat-square&logo=telegram&logoColor=white) ![Discord](https://img.shields.io/badge/Discord-5865F2?style=flat-square&logo=discord&logoColor=white) ![Slack](https://img.shields.io/badge/Slack-4A154B?style=flat-square&logo=slack&logoColor=white) |
| **Security** | ![Fernet](https://img.shields.io/badge/Fernet-1f2328?style=flat-square) ![OS keyring](https://img.shields.io/badge/OS%20keyring-1f2328?style=flat-square) |

<details>
<summary><strong>Channels, integrations and model providers</strong></summary>

| Channel | Status | How to connect |
|---|---|---|
| Terminal | Built in | Always available |
| Telegram | Stable | `alfard channel connect telegram` |
| Discord | Stable | `alfard channel connect discord` |
| Slack | Stable | `alfard channel connect slack` |

| Integration | Status | How to connect |
|---|---|---|
| Notion | Stable | `alfard connect notion` |
| GitHub | Stable | `alfard connect github` |
| Linear | Stable | `alfard connect linear` |
| Web search (DDG / Brave / SearXNG) | Stable | Enabled during setup |
| Gmail | Experimental | `alfard connect gmail` (OAuth via `gogcli`, auto-installed) |
| Google Drive | Experimental | `alfard connect gdrive` (OAuth via `gogcli`, auto-installed) |

| Provider | Runs locally | Models |
|---|---|---|
| OpenRouter | No | `openrouter/auto` (default) · `google/gemini-3-flash-preview` · `anthropic/claude-sonnet-4-6` · any model on the platform |
| OpenAI | No | `gpt-4o` (default) · `gpt-4o-mini` · `o4-mini` · custom |
| Anthropic | No | `claude-sonnet-4-6` (default) · `claude-opus-4-7` · `claude-haiku-4-5-20251001` · custom |
| Ollama | Yes | `llama3.2` · `mistral` · `qwen2.5-coder` · any local model |
| LM Studio | Yes | Any model loaded in LM Studio |

</details>

## Getting started

**Requirements**

- Node.js, for the one-line install, or Python 3.11+ with `pipx`
- An LLM API key, or [Ollama](https://ollama.com) to run fully local

### 1. Install and launch

```bash
npx alfard-cli
```

Alfard installs itself and launches. No Python setup needed. Prefer Python? `pipx install alfard` does the same thing.

### 2. Run setup

```bash
alfard setup
```

Six steps, about three minutes: provider, API key, integrations, first agent, skills, review. With no API key, pick **Ollama** for a fully local setup.

### 3. Open Alfard

```bash
alfard
```

Everything is in the arrow-key menu. Choose an agent from **my agents**, then **run**. To keep it running 24/7, go to **settings → service**.

<details>
<summary><strong>Manual install: Python and pipx, per OS</strong></summary>

**macOS**

```bash
brew install python@3.11 pipx
pipx ensurepath          # then close and reopen the terminal
pipx install alfard
```

**Windows**: install Python 3.11+ from [python.org](https://www.python.org/downloads/) and tick **Add Python to PATH**. Then:

```cmd
pip install pipx
pipx ensurepath
pipx install alfard
```

**Linux**

```bash
sudo apt update && sudo apt install python3.11 python3.11-venv python3-pip -y
pip install pipx && pipx ensurepath
pipx install alfard
```

Check with `python3 --version`; it should say 3.11 or higher.

</details>

<details>
<summary><strong>Power-user commands</strong></summary>

```bash
alfard run <agent>                # run an agent
alfard headless <agent>           # channels only, for a VPS or homelab
alfard service install <agent>    # start on boot, recover from crashes
alfard connect <name>             # connect an integration
alfard channel connect <name>     # connect a channel
alfard log                        # full audit trail
alfard cron                       # manage scheduled tasks
alfard doctor                     # diagnose setup issues
```

</details>

<details>
<summary><strong>Writing an agent by hand</strong></summary>

`alfard` → **create a new agent** runs a two-minute wizard. Or write `soul.md` directly; it's plain Markdown:

```markdown
# postman

## Purpose
You manage email. You read, triage, draft, and send via Gmail.
You never send without explicit user approval.

## Personality
Efficient and direct. Summarise threads in bullet points.

## Rules
- Always show a draft before calling gmail_send_message.
- Mark threads read only after the user confirms.
- Flag anything from investors or customers as high priority.
```

</details>

<details>
<summary><strong>Where your data lives: <code>~/.alfard/</code></strong></summary>

Nothing is ever written to the Alfard repo or install directory.

```text
~/.alfard/
├── .env.enc               # API keys, Fernet-encrypted
├── config/
│   ├── alfard.yaml        # provider, model, approval gate
│   └── integrations.yaml  # channels and integrations
├── agents/<name>/
│   ├── soul.md            # personality and rules
│   ├── skills.yaml
│   ├── brain.db           # memory (SQLite + vectors)
│   ├── memory/            # embeddings + proposals.jsonl
│   └── crons.yaml
├── skills/                # your own skills
└── logs/
    ├── audit.jsonl        # append-only audit trail
    └── cron_jobs.sqlite
```

</details>

## Status and roadmap

Published on PyPI and npm, in active development. Vote on what comes next in [Discussions](https://github.com/waterduckpani/alfard/discussions).

- [x] Approval gate on every channel
- [x] Terminal, Telegram, Discord and Slack
- [x] Background service mode with crash recovery
- [ ] Local web dashboard (v0.2)
- [ ] Agent-to-agent communication
- [ ] Opt-in Docker sandbox for code execution
- [ ] WhatsApp channel
- [ ] Bundled Gmail OAuth, with no GCP setup

## License

MIT. See [LICENSE](https://github.com/waterduckpani/alfard/blob/master/LICENSE).

[Contributing](https://github.com/waterduckpani/alfard/blob/master/CONTRIBUTING.md) · [Security policy](https://github.com/waterduckpani/alfard/blob/master/SECURITY.md) · [Code of conduct](https://github.com/waterduckpani/alfard/blob/master/CODE_OF_CONDUCT.md)

---

<div align="center">
  <sub>Built by <a href="https://github.com/waterduckpani">Bharat Khanna</a> · <a href="https://github.com/waterduckpani?tab=repositories">More projects</a> · If Alfard is useful to you, a ⭐ goes a long way.</sub>
</div>
