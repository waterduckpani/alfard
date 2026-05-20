# Web usage

## Search vs fetch

- Use **web_search** when you need to find information or discover URLs — it's for queries, not known destinations.
- Use **web_fetch** when you already have a specific URL and need the full page content.
- Default to web_search first; only fetch a page once you have a URL worth reading.

## Rules

- Always summarise web results — never dump raw content into the response.
- Cite your sources when using web information (URL or site name is enough).
- If web_search returns no useful results, rephrase the query and try once more before giving up.
- Do not fetch URLs from untrusted sources without telling the user first.
