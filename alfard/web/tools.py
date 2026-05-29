"""Web search and fetch tools — registered as native tools when an agent's web_access.enabled is true."""

import json
import urllib.error
import urllib.parse
import urllib.request

from ddgs import DDGS

from alfard.tools.registry import ToolRegistry
from alfard.web.config import WebConfig

_MAX_FETCH_CHARS = 8_000
_TIME_SIGNALS = {"latest", "current", "today", "now", "breaking", "war", "2026", "news"}


def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    with DDGS() as ddgs:
        if any(s in query.lower() for s in _TIME_SIGNALS):
            raw = list(ddgs.news(query, max_results=max_results))
            return [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("body", "")}
                for r in raw
            ]
        raw = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in raw
        ]


def _brave_search(query: str, api_key: str) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "count": "5"})
    req = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
        for r in data.get("web", {}).get("results", [])[:5]
    ]


def _searxng_search(query: str, base_url: str) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "format": "json"})
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/search?{params}",
        headers={"User-Agent": "alfard/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in data.get("results", [])[:5]
    ]


def _fmt(results: list[dict]) -> str:
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
    return "\n\n".join(lines)


def register_web_tools(registry: ToolRegistry, config: WebConfig) -> None:
    """Register web_search and/or web_fetch based on agent web_access config."""
    if not config.enabled:
        return

    provider = config.search_provider
    brave_key = config.brave_api_key
    searxng_url = config.searxng_url

    if provider != "fetch_only":
        def web_search(query: str) -> str:
            try:
                if provider == "brave":
                    if not brave_key:
                        return "Brave API key not configured."
                    return _fmt(_brave_search(query, brave_key))
                if provider == "searxng":
                    if not searxng_url:
                        return "SearXNG URL not configured."
                    return _fmt(_searxng_search(query, searxng_url))
                return _fmt(_ddg_search(query))
            except Exception as e:
                return f"Search failed: {e}"

        registry.register(
            "web_search",
            "Search the web. Returns top 5 results with title, URL, and snippet.",
            web_search,
            True,
            {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query"}},
                "required": ["query"],
            },
            is_mcp=True,
        )

    if config.fetch_enabled:
        def web_fetch(url: str) -> str:
            try:
                req = urllib.request.Request(
                    f"https://r.jina.ai/{url}",
                    headers={"User-Agent": "alfard/1.0", "Accept": "text/markdown"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read().decode("utf-8", errors="replace")[:_MAX_FETCH_CHARS]
            except urllib.error.HTTPError as e:
                return f"Fetch failed: HTTP {e.code}"
            except Exception as e:
                return f"Fetch failed: {e}"

        registry.register(
            "web_fetch",
            "Fetch the readable text content of a URL as Markdown.",
            web_fetch,
            True,
            {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "The URL to fetch"}},
                "required": ["url"],
            },
            is_mcp=True,
        )
