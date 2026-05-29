# GitHub Skill

## How to reach GitHub tools
Use this routing pattern — strictly in order:

1. `mcp_list_tools(source="github")` — get the full list of available GitHub tools
2. `mcp_invoke(source="github", tool="<tool_name>", arguments={...})` — execute it

**Never call `lazy-tool.invoke_proxy_tool`** — it is hidden and will fail.
**Never call `lazy-tool.search_tools`, `lazy-tool.list_tools`, or `lazy-tool.get_tool_schema`** — they are hidden.
If you are unsure which integrations are connected, call `mcp_list_sources()` first.

Interact with GitHub repositories: read issues, explore code, and perform write operations with explicit user approval.

## When to use it
- User asks about issues, pull requests, or code in a GitHub repo
- User wants to search repositories or find a specific file
- User asks to create an issue or interact with a PR

## Step 1 — Always resolve the authenticated user first

Before any operation that involves an owner, username, or repo list, call the authenticated user endpoint:

```
mcp_invoke(source="github", tool="get_me", arguments={})
```

Use the `login` field from the response as the owner for all subsequent calls.

**Never infer, guess, or read a username from memory, context, or prior conversation.** The authenticated user must be confirmed via `get_me` every time. This prevents acting on the wrong account.

## Step 2 — Resolve the target repository

Before asking "which repository?", check agent memory in this order:

1. **Current conversation** — did the user mention a repo name or owner/repo pair in this session? Use it.
2. **Agent memory (brain.md / memory store)** — is there a stored primary repo or active project? Look for keys like `primary_repo`, `project`, `repo`, or `project_state`. If found, use that repo without asking.
3. **Only ask if no context exists** — if neither the conversation nor memory provides a clear repo, ask the user once: *"Which repository should I use?"* Then store the answer in memory so you don't ask again next time.

When a repo is resolved from memory, confirm it briefly before proceeding: *"Using repo `owner/repo` from memory — is that right?"* If the user says no, update memory with the correct repo.

## Common operations

- Get authenticated user: `mcp_invoke(source="github", tool="get_me", arguments={})`
  — always call this first; use the returned `login` as `owner`
- List the authenticated user's repos: `mcp_invoke(source="github", tool="list_repos", arguments={})`
  — never pass an owner to this call; the API scopes it to the authenticated user automatically
- Get an issue: `mcp_invoke(source="github", tool="get_issue", arguments={"owner": "<from get_me>", "repo": "...", "issue_number": N})`
- Create an issue: `mcp_invoke(source="github", tool="create_issue", ...)` — irreversible, requires approval
- Get file contents: `mcp_invoke(source="github", tool="get_file_contents", arguments={"owner": "<from get_me>", "repo": "...", "path": "..."})`
- Search: `mcp_invoke(source="github", tool="search_repositories", arguments={"query": "..."})`

## Hard rules
- Call `get_me` before any operation that needs an owner or username — no exceptions
- Never derive the owner from git config, memory, or guesswork
- Always confirm repo owner and name before any write operation
- Never push code without showing the diff to the user first
- For PRs: always show what will be merged before calling `merge_pull_request`
