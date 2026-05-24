# GitHub Skill

## How to reach GitHub tools (lazy-tool proxy)
GitHub tools are NOT directly registered. They are proxied through lazy-tool.
Use this routing pattern — strictly in order:

1. `mcp_list_tools(source="github")` — get the full list of available GitHub tools
2. `lazy-tool.invoke_proxy_tool(source="github", tool="<tool_name>", arguments={...})` — execute it

**Never call `lazy-tool.search_tools`** — it is disabled. Use `mcp_list_tools` instead.
**Never call `lazy-tool.list_tools` or `lazy-tool.get_tool_schema`** — they are hidden. `mcp_list_tools` replaces both.
If you are unsure which integrations are connected, call `mcp_list_sources()` first.

Interact with GitHub repositories: read issues, explore code, and perform write operations with explicit user approval.

## When to use it
- User asks about issues, pull requests, or code in a GitHub repo
- User wants to search repositories or find a specific file
- User asks to create an issue or interact with a PR

## Common operations
- List repos: list_repos
- Get an issue: get_issue with owner, repo, issue_number
- Create an issue: create_issue — irreversible, requires approval
- Get file contents: get_file_contents with owner, repo, path
- Search: search_repositories or search_code

## Hard rules
- Always confirm repo owner and name before any write operation
- Never push code without showing the diff to the user first
- For PRs: always show what will be merged before calling merge_pull_request
