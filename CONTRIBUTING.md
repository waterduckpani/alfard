# Contributing to Alfard

## Contents

1. [Dev setup](#1-dev-setup)
2. [Running tests](#2-running-tests)
3. [Adding a new integration](#3-adding-a-new-integration)
4. [Adding a new channel](#4-adding-a-new-channel)
5. [Adding a custom skill](#5-adding-a-custom-skill)
6. [PR process](#6-pr-process)

---

## 1. Dev setup

**Prerequisites:** Python 3.11+, Node.js (for MCP servers via `npx`)

```bash
git clone https://github.com/waterduckpani/alfard.git
cd alfard
pip install -e ".[dev]"
alfard setup
```

`alfard setup` runs the interactive wizard and writes your config to `~/.alfard/config/alfard.yaml`. It asks for your LLM provider and API key. You only need to run it once.

To verify everything is wired up:

```bash
alfard list          # should print your agents (empty on first run)
alfard status        # shows provider and connected integrations
```

If you installed via `pip install -e .` without `[dev]`, add the test dependencies separately:

```bash
pip install pytest pytest-asyncio
```

---

## 2. Running tests

```bash
pytest tests/ -v
```

All 24 tests must pass before you open a PR. The suite lives in `tests/test_memory.py` and covers `MemoryManager`: writes, retrieval scoring, goal lifecycle, caps, and the reflect pipeline.

Tests are fully offline — all embedding API calls are monkeypatched to a deterministic local function. No LLM key is needed.

To run a single test:

```bash
pytest tests/test_memory.py::test_reflect_deduplicates_proposals -v
```

---

## 3. Adding a new integration

An integration is an MCP server that alfard can connect and disconnect via `alfard connect <name>` and `alfard disconnect <name>`.

### 3a. Add a catalogue entry

Add one entry to the `CATALOGUE` dict in `alfard/integrations/catalogue.py`:

```python
"your_service": {
    "display_name": "Your Service",
    "auth": AUTH_APIKEY,                    # or AUTH_OAUTH for OAuth flow
    "description": "One line on what it does.",
    "credential_env": "YOUR_SERVICE_TOKEN", # env var that holds the credential
    "get_token_url": "https://...",         # where users get a token
    "get_token_steps": (
        "1. Go to ...\n"
        "2. Create an API key\n"
        "3. Copy it — it starts with ..."
    ),
    "mcp_transport": "stdio",
    "mcp_command": "npx",
    "mcp_args": ["-y", "@your-org/your-mcp-server"],
    "mcp_url": "",
    "reversible_tools": [
        "list_items", "get_item", "search_items",
    ],
    "irreversible_tools": [
        "create_item", "update_item", "delete_item",
    ],
},
```

Rules for the tool lists:
- Every tool exposed by the MCP server must appear in exactly one list.
- `reversible_tools` — read-only or easily undone (list, get, search).
- `irreversible_tools` — creates, updates, deletes, sends. These hit the approval gate before executing.

If you use `AUTH_OAUTH`, set `"mcp_transport": "gws"` and follow the pattern in the `gmail` and `gdrive` entries. The GWS OAuth flow is handled by `alfard connect your_service`.

### 3b. Add a skill file

Create `skills/your_service.md` with concise rules for how the agent should use the integration. Keep it under 30 lines. Format:

```markdown
# Your Service Skill

## Key behaviours
- Always confirm before deleting anything.
- Summarise results — never paste raw API responses.

## Tool use
Call list_items first, then get_item for the specific record.
```

Agents pick up skills via `alfard skill add <agent> your_service`.

### 3c. Test manually

```bash
alfard connect your_service   # should prompt for token and store it
alfard run your_agent         # ask the agent to list items from your service
alfard disconnect your_service
```

---

## 4. Adding a new channel

A channel is an interface through which a user talks to an agent — terminal, Slack, Telegram, Discord are the existing ones. Adding a new channel has four steps.

### 4a. Create the channel file

Create `alfard/channels/<name>.py`. Your class must extend `BaseChannel` from `alfard/channels/base.py` and implement all four abstract methods:

```python
"""<Name> channel — <one-line description>."""

from alfard.channels.base import BaseChannel


class YourNameChannel(BaseChannel):

    def __init__(self, agent_name: str, orchestrator, audit, loader, registry) -> None:
        self._agent_name = agent_name
        self._orchestrator = orchestrator
        self._audit = audit
        self._loader = loader
        self._registry = registry

    def get_name(self) -> str:
        return "yourname"          # lowercase, no spaces

    def start(self) -> None:
        """Start the channel loop. Block until done."""
        ...

    def stop(self) -> None:
        """Signal the loop to exit."""
        self._orchestrator.stop()

    def notify_memory_write(self, entry: dict) -> None:
        """Show a notification when the agent writes to brain.db.

        entry keys: type, content, source, valence, status.
        Called after the full reply is sent — do not block.
        """
        ...
```

### 4b. Drain memory notifications

After each agent reply, drain the notification buffer and call `notify_memory_write` for each entry:

```python
from alfard.memory.notifications import drain as _drain_notifications

response = orchestrator.run(user_message)

for entry in _drain_notifications():
    self.notify_memory_write(entry)
```

The terminal channel in `alfard/channels/terminal.py` is the canonical reference.

### 4c. Wire the approval gate

If your channel is interactive (users can approve/reject actions in real time), pass a custom notifier to `build_orchestrator`:

```python
from alfard.orchestrator.builder import build_orchestrator

orchestrator, audit, loader, registry = build_orchestrator(
    agent_name=agent_name,
    notifier=YourNotifier(),  # implements show_approval_request()
    gate_enabled=True,
)
```

For background channels (Slack bot, Telegram bot), the default `CLINotifier` sends approval prompts to stdout. Override it with a notifier that posts an approval message to your channel and waits for user response.

### 4d. Register the channel

In whatever CLI command or entry point starts your channel, create the channel instance and register it with `ChannelManager`:

```python
from alfard.channels.manager import ChannelManager
from alfard.channels.yourname import YourNameChannel

manager = ChannelManager()
manager.set_audit(audit)
manager.register(YourNameChannel(agent_name, orchestrator, audit, loader, registry))
manager.start_all(main_channel="yourname")
```

### 4e. Handle /new and /remember

Slash commands are dispatched by `alfard/commands/registry.py`. You do not need to implement them — just call `dispatch()` before forwarding input to the orchestrator:

```python
from alfard.commands.registry import is_command, dispatch

if is_command(user_input):
    context = {
        "agent_name": agent_name,
        "memory": orchestrator._memory,
        "loader": loader,
        "tool_registry": registry,
        "llm": orchestrator._llm,
        "orchestrator": orchestrator,
    }
    reply = dispatch(user_input, context)
    if reply:
        send_to_user(reply)
else:
    reply = orchestrator.run(user_input)
    send_to_user(reply)
```

All built-in commands (`/new`, `/remember`, `/reset`, `/status`, `/skills`, `/help`, `/model`, `/que`, `/guide`) are registered automatically by `build_orchestrator` via `register_all()`. To add a new command, add a handler function to `alfard/commands/handlers.py` and register it inside `register_all()`.

---

## 5. Adding a custom skill

A skill is a Markdown file that gets injected into an agent's system prompt. It contains concise rules for a specific domain or tool.

**Global skills** (available to all agents) live in `skills/`:

```
skills/
  gmail.md
  github.md
  your_skill.md   ← add yours here
```

**Per-agent skills** live in the agent's directory:

```
~/.alfard/agents/<agent-name>/skills/
  your_skill.md
```

Skill file format — keep it short (under 40 lines):

```markdown
# Skill Name

## When to use
One sentence on the trigger condition.

## Behaviour
- Rule one.
- Rule two.
- What to never do.

## Tool guidance
Which tool to call first, what arguments matter, what to check in the result.
```

Attach a skill to an agent:

```bash
alfard skill add <agent> your_skill
```

Remove it:

```bash
alfard skill remove <agent> your_skill
```

---

## 6. PR process

### Branch naming

```
feat/short-description       # new feature
fix/short-description        # bug fix
docs/short-description       # documentation only
refactor/short-description   # no behaviour change
```

### Commit style

Use the conventional commits format: `type: short description in present tense`

```
feat: add Telegram channel
fix: drain notifications after approval-gated tool calls
docs: document skill file format
refactor: extract channel boot sequence into helper
```

One logical change per commit. Don't bundle unrelated fixes.

### CHANGELOG entry

Every PR that changes user-facing behaviour must include an entry in `CHANGELOG.md` under the `[Unreleased]` section (create it above the latest version header if it doesn't exist):

```markdown
## [Unreleased]

### Added
- Added Telegram channel with inline approval gate notifications

### Fixed
- Fixed memory notification drain being skipped on KeyboardInterrupt
```

Follow the [keepachangelog](https://keepachangelog.com) format: `### Added`, `### Fixed`, `### Changed`, `### Removed`.

### Before opening the PR

Run the full test suite:

```bash
pytest tests/ -v
```

All 24 tests must pass.

### PR checklist

The PR template at `.github/PULL_REQUEST_REMPLATE.md` lists the full checklist. The required items are:

- [ ] All 24 tests pass
- [ ] CHANGELOG.md updated
- [ ] No new dependencies added to `pyproject.toml` without discussion
- [ ] Every tool in a new integration is classified as reversible or irreversible
- [ ] Security layers (sanitizer, approval gate, audit log, tool registry) are not bypassed or stubbed
