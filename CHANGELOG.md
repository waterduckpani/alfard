# Changelog
All notable changes are documented here.
Format: https://keepachangelog.com
Versioning: https://semver.org

---

## v0.1.26 — 2026-06-05

### Security
- Fixed approval gate not being restored after cron job with gate disabled (telegram_bot.py) — after a cron run with approval_gate: disabled, all subsequent user messages in the same session were silently bypassing the approval gate. Gate state is now saved before the cron run and restored in a finally block regardless of outcome.

---

## v0.1.25 — 2026-06-02

### Fixed
- CRON_ALWAYS_GATE no longer blocks gmail_send_message when a cron job has gate disabled. Users who explicitly disable the gate with "I understand" confirmation can now run email-sending cron jobs without approval prompts. Truly destructive tools (delete_file, push_code, run_script, etc.) remain unconditionally gated.
- Cron gate disable setting was being silently ignored — approval_gate: disabled was present in crons.yaml but inject_cron_message was discarding it and never passing it to the orchestrator session. Gate always started as enabled regardless of user configuration. Fixed across Slack, Telegram, and Discord channel bots — gate_disabled is now correctly extracted from job config and passed through to the orchestrator, which sets gate.enabled = False before execution.

---

## v0.1.24 — 2026-06-02

### Fixed
- gmail_send_draft was added to gws_tools.py in v0.1.23 but was missing from gog_tools.py — the file actually used at runtime. Added gmail_send_draft registration to gog_tools.py marked as irreversible so the approval gate fires before sending.

---

## v0.1.23 — 2026-06-02

### Added
- gmail_send_draft tool — sends an existing draft exactly as-is via the Gmail API drafts.send endpoint, preserving all HTML formatting, attachments, and headers. Registered as irreversible so the approval gate always fires before sending.

### Fixed
- Agent no longer reconstructs draft content via gmail_get_draft + gmail_send_message when asked to send a draft. Gmail skill updated with explicit rule to always use gmail_send_draft with the draft ID.

---

## v0.1.22 — 2026-06-02

### Fixed
- Approval gate: replaced raw JSON argument dumps with clean human-readable summaries across all channels (Telegram, Slack, Discord, CLI, terminal). New formatter module (alfard/gate/formatter.py) with human_label() and action_summary() — no JSON ever shown to the user
- Telegram approval gate: "Message is too long" error resolved — long email bodies no longer included in approval messages
- Gmail tools: approval prompt now shows To, Subject, and body character count instead of full email content

---

## v0.1.21 — 2026-06-02

### Fixed
- Telegram approval gate: switched from Markdown to HTML parsing with html.escape() on all user-facing content — prevents email bodies with special characters from breaking message delivery and causing silent auto-reject
- Slack approval gate: unhandled API exceptions now caught cleanly — failure sends user notification and returns "n" instead of crashing the gate
- Discord approval gate: send failures no longer silently wait out the 300-second timeout — fails immediately with user notification
- CLI input: "yes" and "no" now accepted at approval prompts in addition to "y" and "n"

---

## [0.1.20] — 2026-06-02

### Added
- Agent deletion — delete agent from my agents submenu or via alfard delete <agent>. Requires typing the agent name to confirm. Stops running daemon before deleting. Path traversal protected.
- Model list updated — OpenRouter now shows gemini-3-flash-preview, claude-sonnet-4.6, deepseek/deepseek-v4-flash, minimax/minimax-m3. Anthropic and OpenAI updated to latest models. Ollama and LM Studio are custom-entry only.

### Fixed
- Credentials hot-reload — connecting a new integration while daemon is running now takes effect immediately, no restart needed
- Channel watchdog — detects dead Telegram/Slack/Discord threads, restarts automatically, alerts user after 3 consecutive failures
- Stale binary detection — daemon notifies via connected channels when pipx upgrade has installed a newer version. alfard doctor checks this too.

### Security
- Agent deletion requires exact name confirmation — no accidental deletion possible
- Deletion path validated strictly inside AGENTS_DIR before any file operation

---

## [0.1.18] — 2026-06-01

### Added
- npx install shim — users can now install and launch Alfard with a single command: npx alfard-cli
- Automated release workflow — pushing a version tag now automatically publishes to PyPI, npm, and creates a GitHub Release with changelog notes

---

## [0.1.17] — 2026-06-01

### Added
- md_convert.py — shared markdown converter module with to_slack(), to_telegram_html(), to_discord()
- Slack responses now render bold, italic, bullets, headings, and links correctly using mrkdwn format
- Telegram responses now render with parse_mode=HTML — bold, italic, code blocks, links all formatted
- Discord responses sanitised — headings flattened to bold, everything else passes through native rendering
- Reflect idle and session-count triggers now notify user in Slack, Telegram, and Discord when proposals are generated

### Fixed
- Raw markdown symbols (**bold**, ###, -bullets) no longer appear as literal text in Slack or Telegram
- Telegram HTML special characters escaped correctly — bare & < > won't silently drop messages

---

## [0.1.16] — 2026-06-01

### Added
- Cron is now a scheduled prompt — fires into a live channel session (Slack, Telegram, Discord) identical to a user typing the message. Sessions stay alive for follow-up replies.
- IPC routing for "run job now" — CLI force-run goes through the daemon via Unix socket, routing through the live bot. Falls back to terminal if no daemon.
- Per-job cron session isolation — each job gets its own clean session key (channel:cron:job_name), separate from the main chat session.
- Approval gate works through live session — gmail_send_message and other irreversible tools trigger Slack/Telegram/Discord approval buttons natively via the session's ApprovalGate.
- Scheduler hot-reload — jobs added or removed via CLI are picked up within 30 seconds, no restart needed.
- Per-job timezone — stored at creation time, displayed in cron list, passed correctly to APScheduler.
- bot_registry.py — process-level registry mapping (agent_name, channel) to live bot instance.
- Concise cron output — job summaries truncated to 500 chars, no verbose reasoning dumps.
- Telegram cron support — cron jobs route to Telegram sessions correctly.
- Discord cron support — same pattern.

### Fixed
- Scheduler cleared and reloaded from crons.yaml on every startup — stale deleted jobs no longer persist.
- CRON_ALWAYS_GATE tool name corrected to gmail_send_message (was send_email).
- Approval button handler now resolves cron sessions (channel:cron:job_name keys) correctly.
- channel_not_found error fixed — notifier always uses raw channel ID, not session key.
- All 8 issues from the cron audit report fixed.

### Security
- Irreversible tool calls in cron sessions require explicit human approval via channel button — same gate as interactive sessions.
- Cron sessions isolated from main chat history.

### Architecture
- Deleted: CronChannelGate, _CronDenyGate, _CronPermissiveGate, _make_cron_gate, _make_slack_notifier, _make_discord_notifier, _make_telegram_notifier, _send_job_summary, _post_via_channel, _handle_cron_thread_reply, _handle_cron_reply, _active_gate, set_active_gate, get_active_gate — all replaced by live session routing.

---

## [0.1.15] — 2026-05-29

### Added
- Channel-routed approval gate for cron jobs — when a scheduled job hits an irreversible action, the approval request is sent to the configured channel (Telegram, Discord, or Slack) and the job waits up to 30 minutes for a response; auto-denies on timeout
- Per-job and global approval_channel config in crons.yaml and alfard.yaml
- Approval channel selection added to the cron creation wizard
- approval_gate: disabled option for cron jobs — requires typing "I understand" in the wizard; emits audit warning on every run; CRON_ALWAYS_GATE tools (send, delete, external writes) remain gated regardless
- CRON_ALWAYS_GATE — irreversible tools that cannot be bypassed even with approval gate disabled: all send tools, delete tools, external write tools, file_write, file_append

### Fixed
- Cron runner now uses build_orchestrator() factory — Gmail, Notion, GitHub and all other integrations were silently missing in all scheduled runs
- Cron runner was checking for gws (removed predecessor) instead of gog for Gmail
- Cron runner was calling MCPClient.connect_all() directly, bypassing lazy-tool proxy — caused [mcp] connected to 0/0 servers
- Cron runner was not registering folder mounts, web tools, or memory tools

### Security
- CRON_ALWAYS_GATE enforced unconditionally — send/delete/external write tools require approval in cron regardless of approval_gate setting
- Disabled approval gate logs audit warning on every job run
- gate_timeout audit event logged when 30 minute window expires

---

## [0.1.14] — 2026-05-29

### Fixed
- Cron jobs now use the same build_orchestrator() factory as alfard run — fixes Gmail, Notion, GitHub and all other integrations silently missing in scheduled runs
- Cron runner was checking for gws (removed predecessor) instead of gog for Gmail credential detection — Gmail tools were never registered in any cron session
- Cron runner was calling MCPClient.connect_all() directly, bypassing the lazy-tool proxy — caused [mcp] connected to 0/0 servers on all MCP-backed integrations
- Cron runner was not registering folder mounts, web tools, or memory tools — all three now included via build_orchestrator()

---

## [0.1.13] — 2026-05-29

### Fixed
- Approval gate no longer crashes with "EOF when reading a line" — CLINotifier.present() catches EOFError and returns "n" (deny)
- Terminal approval gate now shows full tool arguments as a formatted JSON panel — users no longer approve blind
- Discord approval gate — any channel member could approve/reject agent actions; now only the session owner can interact with the buttons
- Discord approval gate — timed-out buttons now disable and show "⏱ Timed out — action rejected" instead of remaining visually active
- Slack approval gate — session owner assignment was outside the per-channel lock; concurrent messages could mis-route gate authority
- Slack approval gate — arguments exceeding 2900 chars now truncated with a notice before posting to avoid Slack API limit failures
- Telegram approval gate — send failures were swallowed silently; gate now logs the failure, resolves to deny immediately, and attempts a fallback message
- Slack sessions now trigger memory reflection (idle watcher, turn counter, session end) — was completely unwired
- Slack "thinking..." stub message now deleted before the real response posts
- Discord and Telegram /remember handler notifications now block until delivered instead of fire-and-forget
- Discord memory notification embeds now use green (0x2ECC71) instead of blurple — clear visual distinction from approval gate requests

---

## [0.1.12] — 2026-05-29

### Fixed
- `mcp_list_sources` now runs in-process (`is_mcp=True`) — the closure captures the live `ToolRegistry` instance and could not be pickled by the sandbox's `ProcessPoolExecutor`, causing a `PicklingError` at runtime whenever the agent called this tool.

---

## [0.1.11] — 2026-05-29

### Security
- Fixed approval gate cross-integration bypass — mcp_invoke approval is now scoped per integration (notion, github, gmail etc.) not per protocol
- Fixed Slack approval gate — only the session owner can approve or reject irreversible actions; other workspace members are blocked with an ephemeral message
- Fixed cron jobs running with no approval gate — added cron_irreversible_policy config (default: deny); irreversible actions in scheduled runs are blocked unless explicitly opted in
- Added SLACK_ALLOWED_USERS env var — restricts which Slack users can talk to the agent, mirroring the existing Telegram allowlist
- Fixed Discord DMs bypassing guild allowlist — DMs now require DISCORD_ALLOWED_USERS when DISCORD_ALLOWED_GUILDS is set; denied by default
- Expanded prompt injection sanitizer from 4 to 19 patterns — covers format headers, role-hijacking phrases, LLM special tokens, and HTML comment injection
- MCP content (email bodies, Notion pages, GitHub PR descriptions, Drive documents) now triggers the behavioural injection gate before subsequent irreversible actions
- Fixed .env file world-readable between alfard connect and alfard run — chmod 600 now applied immediately on write
- Brave API key moved from plaintext agent config to encrypted keystore
- Audit log now redacts sensitive field values (body, content, message, token, key, secret, password) before writing to JSONL
- Binary checksum verification in lazy_tool is now non-optional — mismatch raises a hard error and deletes the file
- Disabled approval gate now emits a loud startup warning on every session instead of silently permitting all actions
- Cron log filename validated against path traversal before write
- Keystore file fallback now emits a one-time warning via sentinel file when OS keyring is unavailable
- Encryption failure now explicitly advises pip install cryptography and warns credentials are unprotected

---

## [0.1.10] — 2026-05-29

### Fixed
- Windows service install no longer requires elevation — `/ru` and `/rl` flags removed from `schtasks /create`
- Added registry autostart fallback (`HKCU\...\Run`) when `schtasks` still fails; no admin rights needed
- `_win_is_installed`, `_win_is_running`, and remove all check both Task Scheduler and registry backends

---

## [0.1.9] — 2026-05-29

### Fixed
- Windows Task Scheduler tasks registered as `alfard-<agent>` at the root instead of inside an `Alfard\` subfolder — avoids "Access is denied" error on Windows versions that require elevation to create subfolders

---

## [0.1.8] — 2026-05-29

### Added
- Service setup step added to the `alfard setup` wizard — users can opt in to run Alfard as a persistent background service during first-run setup

---

## [0.1.7] — 2026-05-29

### Fixed
- `gogcli` install logic moved from `cmd_connect` into `setup/dependencies.py` and made cross-platform — works on macOS, Linux, and Windows

---

## [0.1.6] — 2026-05-28

### Fixed
- Daemon signal handling: `loop.add/remove_signal_handler` (Unix-only) replaced with platform-aware setup; win32 uses `signal.SIGINT`/`SIGBREAK`
- `npx`/`npm` commands in the integration catalogue use `npx.cmd`/`npm.cmd` on win32
- `gogcli` install uses `npm.cmd` on win32
- Keystore `chmod(0o600)` replaced with `_secure_file()` using `icacls` on win32
- Headless SIGTERM guard for win32; SIGBREAK fallback added
- Clipboard copy gains `clip.exe` branch for win32
- `encoding="utf-8"` added to all `open()`/`read_text()`/`write_text()` calls across 13 modules
- Temp paths normalised: `/tmp/` → `tempfile.gettempdir()` in `cmd_connect` and `lazy_tool`
- Doctor and uninstall stale-binary checks wrapped in platform guard; win32 checks `LOCALAPPDATA`/`APPDATA`
- PATH separator hardcoded `":"` replaced with `os.pathsep` in `lazy_tool`
- `schtasks` error message corrected for win32 context in `cmd_service`

---

## [0.1.5] — 2026-05-28

### Fixed
- Banner file read now specifies `encoding="utf-8"` — prevents `UnicodeDecodeError` crash on startup on Windows systems where the default ANSI code page is not UTF-8

---

## [0.1.4] — 2026-05-27

### Added
- Cross-platform persistent agent service (Linux systemd, macOS launchd, Windows Task Scheduler)
- `alfard daemon` — unified channels + crons + IPC server running in the background
- `alfard run` connects to a live daemon when one is running, falling back to in-process mode
- `alfard doctor` — 2 new service health checks (daemon socket, service registration)

### Changed
- Top-level menu restructured to 8 items with clean submenus
- 16 UX fixes across all menus (Rich style removed from uninstall, service menu clear, edit help, mount confirm/restart, service remove hint, create gate, TUI menu labels, cron confirm/hints)

---

## [0.1.3] — 2026-05-26

### Added
- `alfard doctor` command — checks binary install, Python dependencies, agents directory, and skills availability; prints a clear pass/fail report
- `alfard uninstall` command — removes the installed binary, user data at `~/.alfard`, and any stale PATH entries
- Uninstall option added to the settings and setup menu

### Fixed
- Skills directory moved inside the package so `pipx` installs no longer ship an empty skills list
- Lazy-tool auto-installs during `alfard setup` with no option to skip, preventing partially configured setups
- OSC 11 background-colour probe added for accurate light-terminal detection on terminals that support it

---

## [0.1.2] — 2026-05-24

### Added
- `mcp_invoke` and `mcp_get_schema` tools replace LLM-synthesised proxy names — MCP tool invocation is now deterministic and does not depend on the LLM guessing a server prefix
- GitHub and Notion skills updated to use `mcp_invoke` directly
- Guided GCP setup wizard (`alfard connect gmail`) always walks through all three setup steps (enable APIs, create OAuth client, download credentials) so users are never dropped into a partial flow

### Changed
- Gmail and GDrive OAuth migrated from `gws` to `gogcli` — simpler installation, better error messages, no GCP project required for bundled credentials
- `gogcli` is auto-installed during `alfard connect gmail` when not already present
- Headless auth flow: OAuth URLs are printed to stdout and an `scp` fallback is shown when a browser cannot be opened (server / SSH environments)
- Conversation history capped at 20 messages to keep context windows bounded; oldest turns are pruned automatically when the limit is reached
- System prompt re-injection every 5 turns removed — injecting the system prompt mid-conversation caused context pollution and inconsistent behaviour

### Fixed
- Keyring path corrected to `gog/data/keyring` so Gmail tool registration resolves credentials at runtime
- OSC 8 hyperlink escape codes stripped from `gogcli` stdout before the output is parsed, preventing broken token extraction on terminals that emit hyperlink annotations
- `invoke_proxy_tool` hidden from LLM tool schema so the model never tries to call the internal proxy directly
- `mcp_invoke` and `mcp_get_schema` marked `is_mcp=True` so the sanitizer is applied and the sandbox can pickle the closures correctly
- `ExceptionGroup` errors from MCP connections are recursively flattened into readable single-line messages
- `mcp_list_tools` now queries the live MCP server for accurate tool names instead of reading a stale catalogue snapshot

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
