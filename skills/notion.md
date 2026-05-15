# Notion Skill

## How Notion MCP works
The Notion MCP server uses the 2025-09-03 API. Databases are
called "data sources" in this version.

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

## Permissions
If a 404 is returned, tell the user to open the page/database
in Notion, click "..." → Connections → add the integration.
Do not retry with a different ID guess.

## Common mistakes to avoid
- Using "database" instead of "data_source" in search filters
- Using a nested ID instead of the top-level ID
- Retrying a 404 with a different ID instead of telling the
  user to share the page
