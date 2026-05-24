"""gog tools — registers gogcli commands as native alfard tools using subprocess."""

import os
import subprocess
from alfard.tools.registry import ToolRegistry


def _gog_env() -> dict:
    from alfard.paths import ALFARD_HOME
    from alfard.security.keystore import get_or_create_gog_password
    env = os.environ.copy()
    env["GOG_HOME"] = str(ALFARD_HOME / "gog")
    env["GOG_KEYRING_BACKEND"] = "file"
    env["GOG_KEYRING_PASSWORD"] = get_or_create_gog_password()
    return env


def _run_gog(*args) -> str:
    result = subprocess.run(
        ["gog"] + list(args),
        capture_output=True,
        text=True,
        env=_gog_env(),
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"gog error: {result.stderr.strip()}")
    return result.stdout.strip()


# ── Gmail ──────────────────────────────────────────────────────────────────


def gmail_list_messages(max_results: int = 10, query: str = "") -> str:
    search = query if query else "is:unread newer_than:3d"
    return _run_gog(
        "gmail", "search", search,
        "--max", str(max_results),
        "--json", "--no-input", "--wrap-untrusted",
    )


def gmail_get_message(message_id: str) -> str:
    return _run_gog(
        "gmail", "get", message_id,
        "--sanitize-content", "--json", "--no-input",
    )


def gmail_search_messages(query: str, max_results: int = 10) -> str:
    return _run_gog(
        "gmail", "search", query,
        "--max", str(max_results),
        "--json", "--no-input", "--wrap-untrusted",
    )


def gmail_list_labels() -> str:
    return _run_gog("gmail", "labels", "--json", "--no-input")


def gmail_get_thread(thread_id: str) -> str:
    return _run_gog(
        "gmail", "thread", "get", thread_id,
        "--full", "--json", "--no-input", "--wrap-untrusted",
    )


def gmail_create_draft(to: str, subject: str, body: str) -> str:
    return _run_gog(
        "gmail", "drafts", "create",
        "--to", to, "--subject", subject, "--body", body,
        "--no-input",
    )


def gmail_send_message(to: str, subject: str, body: str) -> str:
    return _run_gog(
        "gmail", "send",
        "--to", to, "--subject", subject, "--body", body,
        "--no-input",
    )


def gmail_thread_modify(thread_id: str, add_label: str = "", remove_label: str = "") -> str:
    args = ["gmail", "thread", "modify", thread_id, "--no-input"]
    if add_label:
        args += ["--add", add_label]
    if remove_label:
        args += ["--remove", remove_label]
    return _run_gog(*args)


def register_gmail_tools(registry: ToolRegistry) -> None:
    """Register Gmail tools using gogcli."""
    tools = [
        ("gmail_list_messages", "List or search emails in Gmail inbox",
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
        ("gmail_search_messages", "Search emails by query",
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
        ("gmail_thread_modify", "Add or remove labels on a thread (e.g. archive)",
         gmail_thread_modify, False,
         {"type": "object", "properties": {
             "thread_id": {"type": "string"},
             "add_label": {"type": "string", "description": "Label to add"},
             "remove_label": {"type": "string", "description": "Label to remove"},
         }, "required": ["thread_id"]}),
    ]
    for name, desc, fn, reversible, params in tools:
        try:
            registry.register(name, desc, fn, reversible, params, is_mcp=True)
        except ValueError:
            pass


# ── Google Drive ───────────────────────────────────────────────────────────


def gdrive_list_files(max_results: int = 10, parent: str = "") -> str:
    args = ["drive", "ls", "--json", "--no-input"]
    if parent:
        args += ["--parent", parent]
    args += ["--max", str(max_results)]
    return _run_gog(*args)


def gdrive_search(query: str, max_results: int = 10) -> str:
    return _run_gog(
        "drive", "search", query,
        "--max", str(max_results),
        "--json", "--no-input",
    )


def gdrive_get_file(file_id: str) -> str:
    return _run_gog("drive", "get", file_id, "--json", "--no-input")


def gdrive_docs_cat(doc_id: str) -> str:
    return _run_gog("docs", "cat", doc_id, "--json", "--no-input")


def gdrive_sheets_get(spreadsheet_id: str, range_: str) -> str:
    return _run_gog("sheets", "get", spreadsheet_id, range_, "--json", "--no-input")


def register_gdrive_tools(registry: ToolRegistry) -> None:
    """Register Google Drive tools using gogcli."""
    tools = [
        ("gdrive_list_files", "List files in Google Drive",
         gdrive_list_files, True,
         {"type": "object", "properties": {
             "max_results": {"type": "integer"},
             "parent": {"type": "string", "description": "Folder ID to list within"},
         }}),
        ("gdrive_search", "Search Google Drive files by name or content",
         gdrive_search, True,
         {"type": "object", "properties": {
             "query": {"type": "string", "description": "Search query"},
             "max_results": {"type": "integer"},
         }, "required": ["query"]}),
        ("gdrive_get_file", "Get metadata for a specific Drive file",
         gdrive_get_file, True,
         {"type": "object", "properties": {
             "file_id": {"type": "string", "description": "Google Drive file ID"},
         }, "required": ["file_id"]}),
        ("gdrive_docs_cat", "Read the contents of a Google Doc",
         gdrive_docs_cat, True,
         {"type": "object", "properties": {
             "doc_id": {"type": "string", "description": "Google Doc ID"},
         }, "required": ["doc_id"]}),
        ("gdrive_sheets_get", "Read a range from a Google Sheet",
         gdrive_sheets_get, True,
         {"type": "object", "properties": {
             "spreadsheet_id": {"type": "string"},
             "range_": {"type": "string", "description": "A1 notation range, e.g. Sheet1!A1:B10"},
         }, "required": ["spreadsheet_id", "range_"]}),
    ]
    for name, desc, fn, reversible, params in tools:
        try:
            registry.register(name, desc, fn, reversible, params, is_mcp=True)
        except ValueError:
            pass
