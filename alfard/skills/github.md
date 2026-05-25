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

## Common operations
- List the authenticated user's repos: `mcp_invoke(source="github", tool="list_repos", arguments={})`
  — never pass an owner unless the user explicitly gives you one
- Get an issue: `mcp_invoke(source="github", tool="get_issue", arguments={"owner": "...", "repo": "...", "issue_number": N})`
- Create an issue: `mcp_invoke(source="github", tool="create_issue", ...)` — irreversible, requires approval
- Get file contents: `mcp_invoke(source="github", tool="get_file_contents", arguments={"owner": "...", "repo": "...", "path": "..."})`
- Search: `mcp_invoke(source="github", tool="search_repositories", arguments={"query": "..."})`

## Hard rules
- Always confirm repo owner and name before any write operation
- Never push code without showing the diff to the user first
- For PRs: always show what will be merged before calling merge_pull_request
