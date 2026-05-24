# Notion Skill

## How to reach Notion tools (lazy-tool proxy)
Notion tools are NOT directly registered. They are proxied through lazy-tool.
Use this routing pattern — strictly in order:

1. `mcp_list_tools(source="notion")` — get the full list of available Notion tools
2. `lazy-tool.invoke_proxy_tool(source="notion", tool="<tool_name>", arguments={...})` — execute it

**Never call `lazy-tool.search_tools`** — it is disabled. Use `mcp_list_tools` instead.
**Never call `lazy-tool.list_tools` or `lazy-tool.get_tool_schema`** — they are hidden. `mcp_list_tools` replaces both.
If you are unsure which integrations are connected, call `mcp_list_sources()` first.

## How Notion MCP works
The Notion MCP server uses the 2025-09-03 API. Databases are
called "data sources" in this version.

## CRITICAL: Always call tools, never answer from memory
Every single Notion question MUST call a tool to get fresh data.
Never answer a Notion question from memory or previous context.
If you think you know the answer — call the tool anyway.
Search results from previous turns are stale. Always refresh.

## Searching
Always use API-post-search with this exact filter format:
  filter: {value: "data_source", property: "object"}
Never use "database" as the filter value — it returns a 400 error.

## IDs
The correct ID for querying a database is the top-level "id"
field from search results. Never use nested IDs from inside
"parent", "database_id", or other nested fields.
Always call API-post-search first to get fresh IDs.
Never reuse or guess IDs from memory.

## Querying a database
Use API-query-data-source with the data_source_id field.
Example: API-query-data-source({data_source_id: "<top-level id>"})

## Reading pages
Use API-retrieve-a-page with the page id.
Use API-get-block-children to get the content of a page.

## Do not warn about permissions preemptively
If you can see a database in search results, you have access to it.
Query it directly. Only mention permissions if you get a 404.

## Creating a database entry
To add a row to a database, use API-post-database-entries — never API-post-page.
Steps:
1. Call API-post-search with filter {value: "data_source", property: "object"} to get the database ID.
2. Call API-post-database-entries with the top-level database ID as the parent:
   parent: {database_id: "<top-level id from search>"}
   Never pass a page_id as the parent when creating a database entry.

## Common mistakes to avoid
- Calling search_tools — it is disabled; use mcp_list_tools(source="notion") instead
- Using "database" instead of "data_source" in search filters
- Using a nested ID instead of the top-level ID
- Using API-post-page to create a database entry — this causes a permissions error
- Passing a page_id as parent instead of database_id when creating a database entry
- Skipping API-post-search and guessing or reusing a database ID
- Retrying a 404 with a different ID instead of telling the user
- Answering from memory instead of calling the tool
