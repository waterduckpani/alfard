"""GWS tools — registers Google Workspace CLI commands as native
alfard tools using subprocess. Used when gws does not support
MCP transport directly."""

import json
import subprocess
from alfard.tools.registry import ToolRegistry


def _run_gws(*args) -> str:
    """Run a gws command and return stdout as string."""
    result = subprocess.run(
        ["gws"] + list(args),
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"gws error: {result.stderr.strip()}")
    return result.stdout.strip()


def gmail_list_messages(max_results: int = 10, query: str = "") -> str:
    return _run_gws("gmail", "+triage", "--max", str(max_results))


def gmail_get_message(message_id: str) -> str:
    return _run_gws("gmail", "+read", "--id", message_id)


def gmail_search_messages(query: str, max_results: int = 10) -> str:
    return _run_gws("gmail", "+triage", "--max", str(max_results), "--search", query)


def gmail_list_labels() -> str:
    try:
        return _run_gws("gmail", "users", "labels", "list",
                        "--params", json.dumps({"userId": "me"}))
    except RuntimeError as e:
        return f"Could not retrieve data: {e}. Try using gmail_triage instead."


def gmail_get_thread(thread_id: str) -> str:
    try:
        return _run_gws("gmail", "users", "threads", "get",
                        "--params", json.dumps({"userId": "me", "id": thread_id}))
    except RuntimeError as e:
        return f"Could not retrieve data: {e}. Try using gmail_triage instead."


def gmail_triage(max_results: int = 10) -> str:
    return _run_gws("gmail", "+triage", "--max", str(max_results))


def gmail_create_draft(to: str, subject: str, body: str) -> str:
    return _run_gws("gmail", "+send",
                    "--to", to,
                    "--subject", subject,
                    "--body", body,
                    "--dry-run")


def gmail_send_message(to: str, subject: str, body: str) -> str:
    return _run_gws("gmail", "+send",
                    "--to", to,
                    "--subject", subject,
                    "--body", body)


def register_gmail_tools(registry: ToolRegistry) -> None:
    """Register Gmail tools using gws CLI."""

    tools = [
        ("gmail_list_messages", "List emails in Gmail inbox",
         gmail_list_messages, True,
         {"type": "object", "properties": {
             "max_results": {"type": "integer", "description": "Max emails to return"},
             "query": {"type": "string", "description": "Gmail search query"},
         }}),
        ("gmail_get_message", "Get a specific email by ID",
         gmail_get_message, True,
         {"type": "object", "properties": {
             "message_id": {"type": "string", "description": "Gmail message ID"},
         }, "required": ["message_id"]}),
        ("gmail_search_messages", "Search emails",
         gmail_search_messages, True,
         {"type": "object", "properties": {
             "query": {"type": "string", "description": "Gmail search query"},
             "max_results": {"type": "integer", "description": "Max results"},
         }, "required": ["query"]}),
        ("gmail_list_labels", "List Gmail labels",
         gmail_list_labels, True,
         {"type": "object", "properties": {}}),
        ("gmail_get_thread", "Get a full email thread",
         gmail_get_thread, True,
         {"type": "object", "properties": {
             "thread_id": {"type": "string", "description": "Thread ID"},
         }, "required": ["thread_id"]}),
        ("gmail_triage", "Get inbox summary with sender, subject, date",
         gmail_triage, True,
         {"type": "object", "properties": {
             "max_results": {"type": "integer", "description": "Max emails"},
         }}),
        ("gmail_create_draft", "Create an email draft for review",
         gmail_create_draft, False,
         {"type": "object", "properties": {
             "to": {"type": "string"},
             "subject": {"type": "string"},
             "body": {"type": "string"},
         }, "required": ["to", "subject", "body"]}),
        ("gmail_send_message", "Send an email",
         gmail_send_message, False,
         {"type": "object", "properties": {
             "to": {"type": "string"},
             "subject": {"type": "string"},
             "body": {"type": "string"},
         }, "required": ["to", "subject", "body"]}),
    ]

    for name, desc, fn, reversible, params in tools:
        try:
            registry.register(name, desc, fn, reversible, params, is_mcp=True)
        except ValueError:
            pass  # already registered
