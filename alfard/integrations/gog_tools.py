"""gog tools — registers gogcli commands as native alfard tools using subprocess."""

import os
import json
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


def gmail_list_messages(max_results: int = 10, query: str = "") -> str:
    search = query if query else "newer_than:7d"
    return _run_gog("gmail", "search", search, "--max", str(max_results), "--json")


def gmail_get_message(message_id: str) -> str:
    return _run_gog("gmail", "get", message_id, "--json")


def gmail_search_messages(query: str, max_results: int = 10) -> str:
    return _run_gog("gmail", "search", query, "--max", str(max_results), "--json")


def gmail_list_labels() -> str:
    return _run_gog("gmail", "labels", "--json")


def gmail_get_thread(thread_id: str) -> str:
    return _run_gog("gmail", "thread", thread_id, "--json")


def gmail_triage(max_results: int = 10) -> str:
    return _run_gog("gmail", "search", "newer_than:7d", "--max", str(max_results), "--json")


def gmail_create_draft(to: str, subject: str, body: str) -> str:
    return _run_gog("gmail", "send",
                    "--to", to, "--subject", subject, "--body", body,
                    "--draft", "--json")


def gmail_send_message(to: str, subject: str, body: str) -> str:
    return _run_gog("gmail", "send",
                    "--to", to, "--subject", subject, "--body", body, "--json")


def register_gmail_tools(registry: ToolRegistry) -> None:
    """Register Gmail tools using gogcli."""
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
            pass


def register_gdrive_tools(registry: ToolRegistry) -> None:
    """Register Google Drive tools using gogcli."""

    def gdrive_list_files(max_results: int = 10, query: str = "") -> str:
        args = ["drive", "ls", "--max", str(max_results), "--json"]
        if query:
            args += ["--query", query]
        return _run_gog(*args)

    def gdrive_get_file(file_id: str) -> str:
        return _run_gog("drive", "get", file_id, "--json")

    def gdrive_search(query: str, max_results: int = 10) -> str:
        return _run_gog("drive", "ls", "--query", query, "--max", str(max_results), "--json")

    tools = [
        ("gdrive_list_files", "List files in Google Drive",
         gdrive_list_files, True,
         {"type": "object", "properties": {
             "max_results": {"type": "integer"},
             "query": {"type": "string", "description": "Drive search query"},
         }}),
        ("gdrive_get_file", "Get metadata for a specific Drive file",
         gdrive_get_file, True,
         {"type": "object", "properties": {
             "file_id": {"type": "string", "description": "Google Drive file ID"},
         }, "required": ["file_id"]}),
        ("gdrive_search", "Search Google Drive files",
         gdrive_search, True,
         {"type": "object", "properties": {
             "query": {"type": "string", "description": "Drive search query"},
             "max_results": {"type": "integer"},
         }, "required": ["query"]}),
    ]
    for name, desc, fn, reversible, params in tools:
        try:
            registry.register(name, desc, fn, reversible, params, is_mcp=True)
        except ValueError:
            pass
