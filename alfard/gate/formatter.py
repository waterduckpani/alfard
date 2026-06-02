"""Approval gate formatter — converts raw tool arguments into human-readable approval prompts."""

from __future__ import annotations

_HUMAN_LABELS: dict[str, str] = {
    "gmail_send_message":    "Send Email",
    "gmail_create_draft":    "Create Draft",
    "gmail_reply":           "Reply to Email",
    "gmail_forward":         "Forward Email",
    "gmail_delete_message":  "Delete Email",
    "gmail_label_message":   "Label Email",
    "gmail_move_message":    "Move Email",
    "gmail_mark_read":       "Mark Email Read",
    "gmail_mark_unread":     "Mark Email Unread",
    "notion_create_page":    "Create Notion Page",
    "notion_update_page":    "Update Notion Page",
    "notion_delete_page":    "Delete Notion Page",
    "notion_append_block":   "Append to Notion Page",
    "web_search":            "Web Search",
    "file_write":            "Write File",
    "file_delete":           "Delete File",
    "file_move":             "Move File",
    "slack_send_message":    "Send Slack Message",
    "slack_post_message":    "Post Slack Message",
    "github_create_issue":   "Create GitHub Issue",
    "github_create_pr":      "Create Pull Request",
    "github_merge_pr":       "Merge Pull Request",
    "github_close_issue":    "Close GitHub Issue",
    "calendar_create_event": "Create Calendar Event",
    "calendar_delete_event": "Delete Calendar Event",
    "calendar_update_event": "Update Calendar Event",
    "drive_upload_file":     "Upload to Drive",
    "drive_delete_file":     "Delete Drive File",
    "mcp_invoke":            "MCP Tool Call",
}

_IMPORTANT_KEYS = (
    "query", "prompt", "message", "content", "text", "title", "name",
    "subject", "body", "url", "path", "filename", "command", "input",
)


def human_label(tool_name: str, arguments: dict | None = None) -> str:
    """Return a human-readable label for a tool name.

    Pass arguments when tool_name may be 'mcp_invoke' so the real nested
    tool name can be resolved instead.
    """
    if tool_name == "mcp_invoke" and arguments:
        real = arguments.get("tool", "")
        if real:
            return _HUMAN_LABELS.get(real) or real.replace("_", " ").title()
    return _HUMAN_LABELS.get(tool_name) or tool_name.replace("_", " ").title()


def action_summary(tool_name: str, arguments: dict) -> str:
    """Return a single-line human-readable summary of what the action will do."""
    a = arguments or {}

    if tool_name == "mcp_invoke":
        real_tool = a.get("tool", "")
        real_args = a.get("arguments") or {}
        if real_tool:
            return action_summary(real_tool, real_args if isinstance(real_args, dict) else {})
        return _fallback(a)

    if tool_name in ("gmail_send_message", "gmail_create_draft", "gmail_reply", "gmail_forward"):
        to = _first(a, "to", "recipient", "recipients")
        subject = _first(a, "subject", "re")
        parts = []
        if to:
            parts.append(f"To: {_trunc(str(to), 40)}")
        if subject:
            parts.append(f"Subject: {_trunc(str(subject), 60)}")
        return "  ·  ".join(parts) if parts else _fallback(a)

    if tool_name in ("notion_create_page", "notion_update_page"):
        title = _first(a, "title", "name")
        database = _first(a, "database", "database_id", "parent")
        parts = []
        if title:
            parts.append(f"Page: {_trunc(str(title), 60)}")
        if database:
            parts.append(f"in {_trunc(str(database), 40)}")
        return "  ·  ".join(parts) if parts else _fallback(a)

    if tool_name == "web_search":
        query = _first(a, "query", "q", "search_query")
        if query:
            return f"Query: {_trunc(str(query), 80)}"
        return _fallback(a)

    if tool_name in ("file_write", "file_delete", "file_move"):
        path = _first(a, "path", "file_path", "filename", "filepath")
        if path:
            return f"Path: {_trunc(str(path), 80)}"
        return _fallback(a)

    if tool_name in ("slack_send_message", "slack_post_message"):
        channel = _first(a, "channel", "channel_id")
        text = _first(a, "text", "message", "content")
        parts = []
        if channel:
            parts.append(f"To: {_trunc(str(channel), 40)}")
        if text:
            parts.append(_trunc(str(text), 60))
        return "  ·  ".join(parts) if parts else _fallback(a)

    return _fallback(a)


def _first(args: dict, *keys: str):
    for k in keys:
        if k in args and args[k] not in (None, "", [], {}):
            return args[k]
    return None


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _fallback(args: dict) -> str:
    for key in _IMPORTANT_KEYS:
        if key in args and args[key] not in (None, "", [], {}):
            return _trunc(str(args[key]), 80)
    for val in args.values():
        if isinstance(val, str) and val.strip():
            return _trunc(val, 80)
    return ", ".join(args.keys()) or "(no arguments)"
