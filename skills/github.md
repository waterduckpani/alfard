# GitHub Skill

## How to reach GitHub tools (lazy-tool proxy)
GitHub tools are NOT directly registered. They are proxied through lazy-tool.
You MUST use this three-step pattern every time:

1. `lazy-tool.list_tools(source="github")` — get the full list of GitHub tools
2. `lazy-tool.get_tool_schema(tool="<tool_name>", source="github")` — get the schema
3. `lazy-tool.invoke_proxy_tool(tool="<tool_name>", source="github", arguments={...})` — call it

Never try to call a GitHub tool (e.g. list_repos) directly — it is not registered.
Always go through lazy-tool.

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
