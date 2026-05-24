"""Integration catalogue — defines every supported MCP integration,
its auth method, credential instructions, and MCP server config."""

AUTH_APIKEY = "apikey"
AUTH_OAUTH = "oauth"

CATALOGUE: dict[str, dict] = {
    "notion": {
        "display_name": "Notion",
        "auth": AUTH_APIKEY,
        "description": "Read and write pages, databases and tasks in your Notion workspace.",
        "credential_env": "NOTION_TOKEN",
        "get_token_url": "https://www.notion.so/my-integrations",
        "get_token_steps": (
            "1. Go to notion.so/my-integrations and click \"New integration\"\n"
            "2. Give it a name, select your workspace, click Save\n"
            "3. Copy the \"Internal Integration Token\" — it starts with ntn_"
        ),
        "mcp_transport": "stdio",
        "mcp_command": "npx",
        "mcp_args": ["-y", "@notionhq/notion-mcp-server"],
        "mcp_url": "",
        "reversible_tools": [
            "API-post-search",
            "API-get-block-children",
            "API-get-user",
            "API-get-users",
            "API-get-self",
            "API-retrieve-a-page",
            "API-retrieve-a-page-property",
            "API-retrieve-a-block",
            "API-retrieve-a-database",
            "API-retrieve-a-data-source",
            "API-query-data-source",
            "API-list-data-source-templates",
            "API-retrieve-a-comment",
        ],
        "irreversible_tools": [
            "API-post-page",
            "API-patch-page",
            "API-post-database",
            "API-patch-database",
            "API-delete-block",
            "API-patch-block-children",
            "API-append-block-children",
        ],
    },
    "github": {
        "display_name": "GitHub",
        "auth": AUTH_APIKEY,
        "description": "Manage repos, issues, pull requests and code on GitHub.",
        "credential_env": "GITHUB_TOKEN",
        "mcp_env_var": "GITHUB_PERSONAL_ACCESS_TOKEN",
        "get_token_url": "https://github.com/settings/personal-access-tokens/new",
        "get_token_steps": (
            "1. Go to github.com/settings/personal-access-tokens/new\n"
            "2. Give it a name, set expiry\n"
            "3. Under 'Repository access' select 'All repositories'\n"
            "4. Under 'Permissions' expand 'Repository' and set:\n"
            "   Contents: Read-only\n"
            "   Issues: Read and write\n"
            "   Pull requests: Read and write\n"
            "   Metadata: Read-only (auto-selected)\n"
            "5. Click 'Generate token' and copy it — starts with github_pat_"
        ),
        "mcp_transport": "stdio",
        "mcp_command": "npx",
        "mcp_args": ["-y", "@modelcontextprotocol/server-github"],
        "mcp_url": "",
        "reversible_tools": [
            "get_repo", "list_repos", "get_issue", "list_issues",
            "get_pull_request", "list_pull_requests", "get_file_contents",
            "search_repositories", "search_code", "list_commits",
        ],
        "irreversible_tools": [
            "create_issue", "update_issue", "create_pull_request",
            "merge_pull_request", "push_files", "create_repository",
            "delete_file", "create_branch",
        ],
    },
    "linear": {
        "display_name": "Linear",
        "auth": AUTH_APIKEY,
        "description": "Manage issues, projects and cycles in your Linear workspace.",
        "credential_env": "LINEAR_API_KEY",
        "get_token_url": "https://linear.app/settings/api",
        "get_token_steps": (
            "1. Go to linear.app/settings/api\n"
            "2. Click \"Create key\", give it a name\n"
            "3. Copy the key — it starts with lin_api_"
        ),
        "mcp_transport": "stdio",
        "mcp_command": "npx",
        "mcp_args": ["-y", "@linear/mcp-server"],
        "mcp_url": "",
        "reversible_tools": [
            "list_issues", "get_issue", "list_projects",
            "list_teams", "list_cycles", "search_issues",
        ],
        "irreversible_tools": [
            "create_issue", "update_issue", "delete_issue",
            "create_project", "update_project",
        ],
    },
    "slack": {
        "display_name": "Slack",
        "auth": AUTH_APIKEY,
        "description": "Read channels and post messages in your Slack workspace.",
        "credential_env": "SLACK_BOT_TOKEN",
        "get_token_url": "https://api.slack.com/apps",
        "get_token_steps": (
            "1. Go to api.slack.com/apps and click 'Create New App'\n"
            "2. Choose 'From a manifest' and paste the alfard manifest\n"
            "3. Install to your workspace\n"
            "4. Copy the Bot Token (xoxb-) from OAuth & Permissions"
        ),
        "mcp_transport": "stdio",
        "mcp_command": "npx",
        "mcp_args": ["-y", "@modelcontextprotocol/server-slack"],
        "mcp_url": "",
        "reversible_tools": [
            "list_channels", "get_channel_history",
            "get_thread_replies", "list_users", "get_user_profile",
        ],
        "irreversible_tools": [
            "post_message", "reply_to_thread",
            "upload_file", "set_channel_topic",
        ],
    },
    "gmail": {
        "display_name": "Gmail",
        "auth": AUTH_OAUTH,
        "description": "Read, organise and send emails in your Gmail inbox.",
        "credential_env": "GOG_ACCOUNT",
        "get_token_url": "",
        "get_token_steps": (
            "1. alfard will guide you through connecting your Google account\n"
            "2. A browser window will open — sign in and click Allow\n"
            "3. Your credentials are stored locally and never leave your machine"
        ),
        "mcp_transport": "gog",
        "mcp_command": "gog",
        "mcp_args": [],
        "mcp_url": "",
        "reversible_tools": [
            "gmail_list_messages",
            "gmail_get_message",
            "gmail_search_messages",
            "gmail_list_labels",
            "gmail_get_thread",
        ],
        "irreversible_tools": [
            "gmail_send_message",
            "gmail_create_draft",
            "gmail_delete_message",
            "gmail_modify_message",
        ],
    },
    "gdrive": {
        "display_name": "Google Drive",
        "auth": AUTH_OAUTH,
        "description": "Search, read and manage files in your Google Drive.",
        "credential_env": "GOG_ACCOUNT",
        "get_token_url": "",
        "get_token_steps": (
            "1. alfard will guide you through connecting your Google account\n"
            "2. A browser window will open — sign in and click Allow\n"
            "3. Your credentials are stored locally and never leave your machine"
        ),
        "mcp_transport": "gog",
        "mcp_command": "gog",
        "mcp_args": [],
        "mcp_url": "",
        "reversible_tools": [
            "drive_list_files", "drive_get_file",
            "drive_search_files", "drive_get_permissions",
        ],
        "irreversible_tools": [
            "drive_create_file", "drive_delete_file",
            "drive_update_file", "drive_move_file",
            "drive_share_file",
        ],
    },
}
