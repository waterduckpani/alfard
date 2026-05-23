# Changelog
All notable changes are documented here.
Format: https://keepachangelog.com
Versioning: https://semver.org

---

## [0.1.0] — 2026-05-23

### Added

**Core engine**
- Implemented ReAct loop orchestrator wiring LLM, tools, approval gate, sandbox, and audit logger
- Added normalised LLM response format (`content`, `tool_calls`, `raw`) returned by every adapter
- Added session state management and conversation history in the orchestrator
- Added system prompt re-injection every 5 turns to prevent context drift
- Added configurable max-turns limit (20) to prevent runaway loops
- Added orchestrator builder factory for constructing wired sessions from any interface

**LLM providers and adapters**
- Added provider registry covering OpenRouter, OpenAI, Anthropic, Ollama, and LM Studio
- Added OpenAI-compatible adapter for OpenRouter, OpenAI, Ollama, and LM Studio
- Added Anthropic SDK adapter with tool-use support
- Added LLM client router that reads provider from config and instantiates the correct adapter

**Agent system**
- Added agent loader that composes system prompt from soul.md, brain.md, and linked skills
- Added `alfard create` — guided agent creation wizard with onboarding flow and essential skill injection
- Added `alfard edit` — edit agent soul and configuration
- Added `alfard list` — list all agents with optional agent picker
- Added base prompt injected into every agent session
- Added path traversal guard in agent loader (agent name cannot escape the agents directory)
- Added example agent shipped with the repo for reference

**Setup wizard**
- Added `alfard setup` — interactive 6-step first-run CLI wizard
- Added provider selection, model configuration, and API key entry in setup
- Added first agent creation step in setup
- Added cron job configuration step in setup
- Added folder mount configuration step in setup
- Added section clearing and step-progress indicators in setup
- Added inline selectors and done screen in setup

**CLI commands and design**
- Added `alfard run` — run an agent in the terminal with optional agent picker
- Added `alfard connect` — guided integration connect flow
- Added `alfard disconnect` — disconnect an integration with warning indicator
- Added `alfard log` — view audit log with tail, filter, and live-follow modes
- Added `alfard status` — panel-based status showing connected integrations and agent info
- Added `alfard skill` — manage per-agent skills
- Added `alfard cron` — full cron job CLI (add, list, delete, run-history) with guided UX
- Added `alfard mount` — manage folder mounts with access-level change flow
- Added `alfard memory` — memory status command with type breakdown and inline review
- Added `alfard headless` — run multiple channels simultaneously without a terminal session
- Added `alfard service` — systemd service install, start, stop, status
- Added `alfard channel` — connect and disconnect chat channels at runtime
- Added `alfard slack` — guided Slack connect flow
- Added interactive main menu when `alfard` is invoked with no subcommand
- Added Alfard design system theme applied across all CLI commands
- Added custom help formatter (AlfardGroup, AlfardCommand)
- Added panel-based list and status output components
- Added file-based ASCII banner replacing hardcoded wordmark
- Migrated all user data to `~/.alfard` to isolate repo to source code only

**Memory system**
- Added SQLite-backed vector store with per-path write locks for concurrent channel safety
- Added embedding client with per-provider model routing (OpenAI, Qwen, Nomic)
- Added memory manager with separate read and write layers
- Added scored semantic retrieval for memory read layer
- Added structured prompt injection for retrieved memories
- Added conflict detection on memory writes
- Added auto-export of vector memories to brain.md
- Added migration path from legacy memory.md to vector store
- Added reflect mechanism — LLM-driven memory consolidation and deduplication
- Added message-count reflect trigger (configurable interval, default 20 messages)
- Added inactivity reflect trigger (fires after 30 minutes of idle with ≥3 messages)
- Added memory review command for inspecting and curating stored memories
- Added memory notification push system for surfacing new writes across channels
- Added 10 typed memory categories: fact, procedure, mistake, tool_pattern, goal, decision, person, preference, constraint, project_state

**Cron system**
- Added APScheduler-based cron scheduler with SQLite job persistence
- Added cron job runner that executes scheduled tasks in isolated sessions
- Added cron schedule parser supporting cron expressions and interval syntax
- Added per-job linked skill injection into scheduled task prompts
- Added run history stored per job

**Folder mounting**
- Added mount manager that loads per-agent mounts.yaml and validates all paths
- Added file read and write tools enforcing declared access levels (readonly / readwrite)
- Added access-level change flow in the mount CLI menu

**Web access**
- Added DuckDuckGo search tool (text search and news search with time-signal detection)
- Added web fetch tool with 8000-character response limit
- Added per-agent web access configuration (enabled/disabled in soul)

**Slash commands**
- Added command registry shared across CLI, Slack, and all other interfaces
- Added /clear — clears conversation context
- Added /remember — saves the last exchange to brain.md
- Added /reset — resets session memory
- Added /skills — lists active skills for the current agent
- Added /status — shows connected integrations and agent info
- Added /help — lists all available commands
- Added register_all guard to prevent duplicate command registration

**Chat interfaces and channels**
- Added channel manager that starts all channels concurrently in daemon threads
- Added terminal channel as the default interactive interface
- Added Slack bot interface using Socket Mode with per-channel isolated sessions
- Added Slack approval gate notifier that presents review requests as Slack messages
- Added Slack markdown-to-mrkdwn converter for properly formatted responses
- Added Slack MCP tool and Slack bot as separate concerns
- Added Discord bot interface with per-guild-channel isolated sessions
- Added Telegram bot interface with per-user isolated sessions
- Added session timeout and eviction across all chat interfaces (4-hour idle)
- Added memory write notifications surfaced as follow-up messages in chat interfaces

**Integrations and MCP**
- Added MCP protocol client supporting stdio and streamable-HTTP transports
- Added integration catalogue defining auth method, credential instructions, and MCP config for each service
- Added Notion integration via MCP (read/write pages, databases, tasks)
- Added Gmail integration via gws workflow tools (read, triage, send, archive)
- Added bundled OAuth credentials so `alfard connect gmail` skips GCP project setup
- Added Notion search re-ranking for reliable database ID resolution
- Added MCP per-connection timeout
- Added credentials manager that injects API keys and OAuth tokens at tool execution time only

**Packaging and distribution**
- Added pyproject.toml with Hatchling build backend
- Added `alfard` CLI entry point for pipx installation
- Added MIT license
- Added README with feature overview, setup instructions, and demo assets

### Security

- Added approval gate that intercepts every irreversible tool call and requires explicit human confirmation before execution
- Added per-user-turn gate reset so a single approval covers one turn, not individual tool calls
- Added job-level approval gate scoping that prevents one MCP server from approving actions for another
- Added tool registry that makes unregistered tool calls structurally impossible, not just discouraged
- Added tool classifier that labels every registered tool as reversible or irreversible
- Added sanitizer that strips `<system>`, `<instructions>` tags and prompt-injection phrases from all untrusted external content before it enters LLM context
- Added source attribution (`[SOURCE: X] … [END SOURCE]`) wrapper on all sanitized content
- Added sandbox executor that runs every tool call in an isolated OS subprocess with a hard 30-second timeout
- Added worktree manager that directs all agent file operations to a disposable git branch, keeping main untouched
- Added audit logger that writes an append-only JSONL record for every tool call with source, session ID, and UTC timestamp
- Added Fernet encryption for API keys stored at rest, with OS keyring as primary key store and key-file fallback
- Added path traversal guard in mount manager blocking access outside declared mount roots
- Added path traversal guard in agent loader blocking agent names that resolve outside the agents directory
- Added secret blocking in the memory write layer (private keys, tokens, credentials are never written to brain.db)
- Added threading locks in the vector store to prevent concurrent brain.db write conflicts across channels
- Added stdin lock in the approval gate to serialise input access between the gate thread and the command poller
- Added MCP `is_mcp` flag on registered MCP tools so the sanitizer applies automatically to all MCP output
- Added credentials manager security invariant: keys are injected into tool kwargs at execution time only and are never present in LLM context or the audit log
