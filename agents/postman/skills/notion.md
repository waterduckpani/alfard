# Notion Skill

## CRITICAL RULES — follow these every single time, no exceptions

**Rule 1:** ALWAYS call API-post-search FIRST before any query.
Never use an ID from memory, context, or previous messages.
Every session starts fresh. IDs must be retrieved live every time.

**Rule 2:** After searching, extract ONLY the top-level "id" field.
Correct: result["id"]
Wrong: result["parent"]["database_id"] or any other nested field

**Rule 3:** Use this exact search call every time without exception:
API-post-search({filter: {value: "data_source", property: "object"}})
Never use filter value "database" — it returns a 400 error.

**Rule 4:** If you get a 404, do NOT retry with a different ID.
Tell the user to share the database with the Alfard integration.

## Querying a database
After getting the ID from search:
API-query-data-source({data_source_id: "<top-level id from search>"})

## Reading pages
API-retrieve-a-page with the page id.
API-get-block-children to get page content.

## Permissions
If 404: tell user to open the page in Notion → ... → Connections → add Alfard.
