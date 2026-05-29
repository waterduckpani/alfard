# Security

## Philosophy

Security in Alfard is the architecture, not a feature layer bolted on top. Every agent action passes through the same pipeline: tool registry → classifier → approval gate → sandbox executor → sanitizer → audit logger. None of those steps can be bypassed by the agent; they are not optional middleware. The design assumes the LLM and every external data source are untrusted inputs, and gives the human owner the final word on every irreversible action.

---

## Threat model

Alfard is designed to defend against:

- **Prompt injection** — a malicious web page, email, or file body instructs the agent to take actions on behalf of the attacker.
- **Silent irreversible actions** — the agent sends an email, deletes a file, or posts a message without the owner noticing.
- **Credential theft** — an attacker or a compromised tool reads API keys or OAuth tokens out of the agent context.
- **Runaway tool loops** — the agent calls the same infrastructure tool in a tight loop, consuming resources or causing unintended side-effects.

---

## Security layers

### 1. Approval gate

**File:** `alfard/gate/approval.py`

Every tool call is first classified as `reversible` or `irreversible` by `alfard/tools/classifier.py`, which reads the `reversible` flag registered with each tool. Any `irreversible` call pauses the ReAct loop and presents the tool name, full arguments, and source (`user_instruction` vs `tool_result`) to the operator before execution. On `n`, the tool result injected into the conversation is `"Action rejected by user."` — the agent is told explicitly that it was blocked.

The gate is also triggered independently of reversibility when the behavioural injection gate fires (see layer 3).

Both decisions — approved and rejected — are written to the audit log (`gate_approved` / `gate_rejected`) before execution continues.

The gate can be disabled in `config/alfard.yaml` under `approval_gate.enabled`. Disabling it is a deliberate operator choice and is visible in the config file.

---

### 2. Encrypted credentials

**Files:** `alfard/security/keystore.py`, `alfard/integrations/credentials.py`

API keys and OAuth tokens are stored encrypted at `~/.alfard/.env.enc` using Fernet symmetric encryption (`cryptography` library). The encryption key is stored in the OS keyring (macOS Keychain, GNOME Keyring, Windows Credential Store via the `keyring` library). On systems without a keyring, the key falls back to `~/.alfard/.key` with `chmod 600` / `icacls` permissions.

On first run, if a plaintext `~/.alfard/.env` is found (legacy or manual setup), `encrypt_env()` in `keystore.py` reads it, re-writes the contents encrypted, and overwrites the plaintext file with null bytes before deleting it (`_secure_delete`).

At runtime, `CredentialsManager.inject()` resolves credentials from `_store` and merges them into tool arguments immediately before execution. Credentials are never present in the conversation history, never passed to the LLM, and never written to the audit log. This invariant is documented in `alfard/integrations/credentials.py`:

```python
# Security invariant: credentials are never passed to the LLM or
# written to the audit log. They are injected into tool kwargs at
# execution time only and exist in memory for that call alone.
```

---

### 3. Three-layer prompt injection protection

#### Layer 1 — Sanitizer (`alfard/tools/sanitizer.py`)

Every tool result, including error strings, is passed through `sanitize()` before being added to the conversation. The sanitizer:
- Strips `<system>…</system>` and `<instructions>…</instructions>` blocks (case-insensitive, DOTALL).
- Redacts known injection phrases: `ignore previous instructions`, `you are now`, `your new instructions`, `ignore all previous`, and their variants.
- Wraps the result in `[SOURCE: <tool_name>]\n…\n[END SOURCE]` attribution so the LLM always knows where content came from.

This applies unconditionally to all tool output, including error messages (`sanitize(str(result["error"]), source=f"{name}.error")`).

#### Layer 2 — Behavioural gate (`alfard/orchestrator/orchestrator.py`, lines 182–199)

After any web tool (`web_search` or `web_fetch`) returns results, `_web_context_active` is set to `True`. On the next tool call that is not itself a web tool and not in the exemption list (`_INJECTION_EXEMPT`), the orchestrator intercepts and presents an explicit approval panel:

> "The agent read web content and is now calling: `<tool>`. Web pages can contain hidden instructions that hijack agents."

This blocks post-web action sequences (the classic injection pattern: fetch a page → page tells agent to exfiltrate data) from executing silently. The interception is logged via `audit.log_prompt_injection_warning(name, approved)`.

The exemption list covers deterministic Alfard infrastructure tools (`mcp_list_sources`, `mcp_invoke`, etc.) that do not act on user data.

#### Layer 3 — Strip safety net (`alfard/tools/sanitizer.py`, `is_suspicious()`)

`is_suspicious()` scans text for the same injection phrases as a secondary signal. In the orchestrator this is checked as an additional indicator — content can be flagged suspicious even after the regex strips have run, providing defence-in-depth if a new pattern bypasses the strip.

---

### 4. Sandbox executor

**File:** `alfard/sandbox/executor.py`

Non-MCP tool functions run in an isolated child process via `concurrent.futures.ProcessPoolExecutor(max_workers=1)`. Each tool call gets a fresh process. A hard timeout of 30 seconds (`DEFAULT_TIMEOUT`) is enforced via `future.result(timeout=self.timeout)`. If the process exceeds the timeout, the call returns a structured failure and the process is terminated. A crashed tool cannot take down the orchestrator.

MCP tools are executed directly (not via the sandbox) because they run in their own subprocess managed by the MCP client, which provides equivalent process isolation. This is noted in a code comment in the orchestrator.

**Current limitation (documented in code):** the child process inherits the parent's Python path and can make network and filesystem calls unless the tool itself is restricted. Docker-based isolation is the planned Phase 2 upgrade.

---

### 5. Tool registry and classifier

**Files:** `alfard/tools/registry.py`, `alfard/tools/classifier.py`

Every callable the agent can invoke must be registered via `ToolRegistry.register()` before the session starts. The orchestrator's dispatch path checks `registry.is_registered(name)` first — unregistered tool names result in an error injected into the conversation, not execution. There is no fallback execution path for unknown tools.

Each tool is registered with a `reversible: bool` flag. `classify()` reads this flag and returns `REVERSIBLE` or `IRREVERSIBLE`. The orchestrator uses this to decide whether to call the approval gate.

Tools can be hidden from the LLM's schema list with `registry.hide(name)` without being unregistered. Hidden tools remain callable internally but the model never sees them in its tool list, preventing accidental or hallucinated calls to infrastructure meta-tools.

The audit log path is never registered as a writable tool.

---

### 6. Worktree isolation

**File:** `alfard/worktree/manager.py`

When an agent operates on files in a git repository, `WorktreeManager.create()` creates a disposable branch (`agent/<task_id>`) and a temporary working directory via `tempfile.mkdtemp`. The agent's file operations happen on this branch. The `main`/`master` branch is never touched. The operator reviews the diff and decides what to merge. When the task ends, `remove()` tears down the worktree and deletes the branch.

If the working directory is not a git repository, worktree creation is skipped silently (`_enabled = False`).

---

### 7. Full audit trail

**File:** `alfard/audit/logger.py`

Every event is written as a JSONL record to the path specified in `config/alfard.yaml` under `audit.log_path` (default: `logs/audit.jsonl`). The file is opened in append mode with `buffering=1` (line-buffered). Records include a UTC timestamp and session ID.

Logged events:
- `session_start` / `session_end` — agent name, provider, model, outcome, turn count, tool call counts, correction signals detected.
- `llm_call` — provider, model, message count, whether the response was text or a tool call.
- `tool_call` — tool name, arguments, source (`user_instruction` or `tool_result`).
- `tool_result` — tool name, success/failure, error message on failure.
- `gate_decision` / `gate_approved` / `gate_rejected` — tool name, arguments, decision, source.
- `prompt_injection_warning` — tool name, whether it was approved.
- `user_correction` — signal word detected (e.g. "no", "wrong", "don't").

**What is never logged:** credentials. Arguments are logged as-is. It is the responsibility of tool authors to ensure credentials are injected by `CredentialsManager` and are not present in the `arguments` dict that reaches the logger. The credentials manager's invariant enforces this at the point of injection.

---

### 8. Memory secret blocking

**File:** `alfard/memory/manager.py`

Before any content is written to `brain.db`, `_check_secrets()` scans it against eight compiled regex patterns:

| Pattern | Label |
|---|---|
| `-----BEGIN … PRIVATE KEY-----` | private key |
| `sk-[A-Za-z0-9_-]{20,}` | API key (sk- prefix) |
| `AKIA[0-9A-Z]{16}` | AWS access key ID |
| `gh[oprsu]_[A-Za-z0-9]{36}` | GitHub token |
| `AIza[0-9A-Za-z-_]{35}` | Google API key |
| `xox[baprs]-…` | Slack token |
| `bearer [A-Za-z0-9._-]{20,}` (case-insensitive) | bearer token |
| `password=<8+ chars>` (case-insensitive) | password |

If any pattern matches, `write()` returns `"blocked: <label>"` immediately without writing. The memory is never stored, never exported to `brain.md`, and never surfaced in future context.

Memory database files (`brain.db`, `sessions.db`) are created with `os.chmod(path, 0o600)` — owner read/write only.

---

### 9. Channel allowlists

**Files:** `alfard/interfaces/telegram_bot.py`, `alfard/interfaces/discord_bot.py`

**Telegram:** `TELEGRAM_ALLOWED_USERS` is read from the encrypted env store. If set, only Telegram user IDs in the comma-separated list are permitted to send messages. `_is_allowed()` is checked before any message is routed to an orchestrator session. If unset, all users are permitted (suitable for personal bots with no public exposure).

**Discord:** `DISCORD_ALLOWED_GUILDS` restricts which server IDs the bot responds in. DMs are always permitted regardless of this setting. If unset, all guilds are permitted.

**Slack:** Access is controlled via Slack's own OAuth scopes and the bot token. The bot only receives messages it is explicitly mentioned in or DMs; workspace-level access control is delegated to Slack's platform.

---

### 10. No telemetry

Alfard collects no usage data, sends no analytics, and makes no outbound connections except those the agent is explicitly instructed to make. The only network calls are to the LLM provider configured by the operator, MCP servers the operator connects, and tools (web search, integrations) the operator enables.

---

## Responsible disclosure

Do not open a public GitHub issue for security vulnerabilities.

Report privately via:
- **Email:** use the contact on the GitHub profile
- **GitHub private advisory:** Security → Report a vulnerability on this repository

Please include a description of the issue, reproduction steps, and the version you are running. Expect an acknowledgement within 72 hours and a resolution timeline within the first response.

---

## Out of scope for v1

These are known gaps, not oversights:

- **Multi-user deployments.** Alfard is designed for single-owner use. There is no role-based access control, no per-user permission model beyond the channel allowlists, and no tenant isolation.
- **Network-level sandbox isolation.** The sandbox executor provides process isolation with a timeout, but child processes inherit the parent's network access. A malicious tool can make arbitrary outbound connections. Docker-based isolation is the planned Phase 2 upgrade.
- **Audit log integrity.** The audit log is an append-only flat file. It is not signed or tamper-evident. An attacker with filesystem access can modify it.
- **MCP server trust.** Alfard connects to MCP servers configured by the operator. It does not verify MCP server identity or sandbox MCP server behaviour beyond what the MCP protocol itself provides.
- **Rate limiting.** There is no built-in rate limiting on channel interfaces. A Telegram or Discord account with access can send unlimited messages.
