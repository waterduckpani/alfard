"""Authenticates and wires up a third-party integration (e.g. Gmail, Slack)."""

import re
import os
import subprocess
import sys
import shutil
import webbrowser
import click
from alfard.cli.help_formatter import AlfardCommand
import yaml
from pathlib import Path
from alfard.integrations.catalogue import CATALOGUE, AUTH_APIKEY, AUTH_OAUTH
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, error_block, alfard_input, alfard_select, alfard_confirm
from alfard.cli.ui_helpers import render_integration_table

_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
_INTEGRATIONS_PATH = Path(__file__).parent.parent.parent / "config" / "integrations.yaml"


def _update_env(key: str, value: str) -> None:
    lines: list[str] = []
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text().splitlines()

    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    updated = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        lines.append(f"{key}={value}")

    _ENV_PATH.write_text("\n".join(lines) + "\n")


def _load_integrations() -> dict:
    if not _INTEGRATIONS_PATH.exists():
        return {"servers": []}
    raw = _INTEGRATIONS_PATH.read_text()
    data = yaml.safe_load(raw)
    if not data:
        return {"servers": []}
    return data


def _save_integrations(data: dict) -> None:
    _INTEGRATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _INTEGRATIONS_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _already_connected(name: str) -> bool:
    data = _load_integrations()
    return any(s["name"] == name for s in data.get("servers", []))


def copy_to_clipboard(text: str) -> bool:
    """Returns True if clipboard copy succeeded."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            return True
        elif sys.platform == "linux":
            subprocess.run(["xclip", "-selection", "clipboard"],
                           input=text.encode(), check=True)
            return True
    except Exception:
        return False
    return False


def _ask_agent_assignment(display: str) -> tuple[str, str]:
    """Return (agent_name_or_'all agents', added_to_label)."""
    from alfard.agents.loader import list_agents, add_skill
    agents = list_agents()
    added_to: str = ""
    if not agents:
        return "", ""

    choices = agents + ["all agents"]
    choice = alfard_select(
        f"which agent should get the {display} skill?",
        choices,
        default=agents[0],
    ) or agents[0]

    if choice == "all agents":
        for a in agents:
            add_skill(a, display.lower().replace(" ", ""))
        added_to = "all agents"
    else:
        add_skill(choice, display.lower().replace(" ", ""))
        added_to = choice

    return choice, added_to


def _derive_team_id(bot_token: str) -> str | None:
    """Call auth.test to derive the Slack team ID from a bot token."""
    import urllib.request
    import json as _json
    req = urllib.request.Request(
        "https://slack.com/api/auth.test",
        headers={"Authorization": f"Bearer {bot_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
            if data.get("ok"):
                return data.get("team_id")
    except Exception:
        return None
    return None


_SLACK_MANIFEST = '''display_information:
  name: alfard
  description: Your local AI agent
  background_color: "#2d2d2d"
features:
  bot_user:
    display_name: alfard
    always_online: true
  app_home:
    home_tab_enabled: false
    messages_tab_enabled: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - chat:write
      - im:history
      - im:read
      - im:write
      - channels:history
      - channels:read
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.im
  interactivity:
    is_enabled: true
  org_deploy_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false'''


def _ensure_slack_bot_token() -> str | None:
    """Return SLACK_BOT_TOKEN, running the full app-creation flow if not already set."""
    from dotenv import load_dotenv as _ldenv
    _ldenv()
    existing = os.environ.get("SLACK_BOT_TOKEN", "")
    if existing.startswith("xoxb-"):
        console.print(f"{dot('ok')} [{p.fg_dim}]using existing bot token.[/]")
        return existing

    console.print(f"[{p.fg_dim}]one-time slack app setup — about 2 minutes.[/]\n")
    console.print(f"[{p.fg_faint}]app manifest:[/]")
    console.print(f"[{p.fg_dim}]{_SLACK_MANIFEST}[/]\n")
    copied = copy_to_clipboard(_SLACK_MANIFEST)
    if copied:
        console.print(f"{dot('ok')} [{p.fg_dim}]manifest copied to clipboard.[/]")
    else:
        console.print(f"[{p.fg_dim}]copy the manifest above manually.[/]")

    console.print(f"\n[{p.fg_em}]step 1 — create a new slack app[/]")
    console.print(
        f"[{p.fg_faint}]  choose 'from an app manifest'\n"
        f"  select your workspace\n"
        f"  paste the manifest (already in your clipboard)\n"
        f"  click 'next', then 'create'[/]"
    )
    webbrowser.open("https://api.slack.com/apps?new_app=1")
    alfard_input("press enter once the app is created", default="")

    console.print(f"\n[{p.fg_em}]step 2 — install to your workspace[/]")
    console.print(
        f"[{p.fg_faint}]  click 'install app' in the left sidebar\n"
        f"  click 'install to workspace'\n"
        f"  click 'allow'[/]"
    )
    alfard_input("press enter once the app is installed", default="")

    console.print(f"\n[{p.fg_em}]step 3 — copy your bot token[/]")
    console.print(
        f"[{p.fg_faint}]  go to 'oauth & permissions' in the left sidebar\n"
        f"  copy the 'bot user oauth token' (starts with xoxb-)[/]"
    )
    bot_token = alfard_input("bot token (xoxb-)", password=True).strip()
    if not bot_token or not bot_token.startswith("xoxb-"):
        console.print(f"\n  [{p.err}]invalid bot token — must start with xoxb-[/]")
        console.print(f"  [{p.fg_faint}]find it under oauth & permissions → bot user oauth token[/]")
        return None
    _update_env("SLACK_BOT_TOKEN", bot_token)
    console.print(f"{dot('ok')} [{p.fg_dim}]bot token saved.[/]")
    return bot_token


def _connect_slack(name: str, integration: dict) -> bool:
    console.print(f"\n[{p.fg_em}]{integration['display_name']}[/]")
    console.print(f"[{p.fg_dim}]{integration['description']}[/]\n")

    bot_token = _ensure_slack_bot_token()
    if not bot_token:
        console.print(f"\n[{p.err}]slack not connected.[/]")
        return False

    console.print(f"[{p.fg_dim}]verifying token...[/]")
    team_id = _derive_team_id(bot_token)
    if not team_id:
        console.print(f"  [{p.err}]could not verify token — check it and try again.[/]")
        return False
    _update_env("SLACK_TEAM_ID", team_id)
    console.print(f"{dot('ok')} [{p.fg_dim}]workspace verified.[/]")

    entry = {
        "name": name,
        "transport": integration["mcp_transport"],
        "command": integration["mcp_command"],
        "args": integration["mcp_args"],
        "env_vars": {
            "SLACK_BOT_TOKEN": "SLACK_BOT_TOKEN",
            "SLACK_TEAM_ID": "SLACK_TEAM_ID",
        },
        "tools": {
            "reversible": integration["reversible_tools"],
            "irreversible": integration["irreversible_tools"],
        },
    }
    data = _load_integrations()
    data.setdefault("servers", [])
    data["servers"] = [s for s in data["servers"] if s["name"] != name]
    data["servers"].append(entry)
    _save_integrations(data)

    _, added_to = _ask_agent_assignment(integration["display_name"])

    console.print(f"\n{dot('ok')} [{p.fg_dim}]slack connected.[/]")
    if added_to and added_to.strip():
        console.print(f"[{p.fg_faint}]skill added to: {added_to.strip()}[/]")
    else:
        console.print(f"  [{p.fg_dim}]create an agent first: alfard create[/]")
    console.print(
        f"\n[{p.fg_faint}]to also run it as a chat bot:[/]\n"
        f"  [{p.fg_em}]alfard connect slack-bot[/]"
    )
    return True


def _connect_slack_bot(name: str, integration: dict) -> bool:
    console.print(f"\n[{p.fg_em}]{integration['display_name']}[/]")
    console.print(f"[{p.fg_dim}]{integration['description']}[/]\n")

    bot_token = _ensure_slack_bot_token()
    if not bot_token:
        console.print(f"\n[{p.err}]slack bot not connected.[/]")
        return False

    console.print(f"\n[{p.fg_em}]app-level token — for socket mode[/]")
    console.print(
        f"[{p.fg_faint}]  open your slack app at api.slack.com/apps\n"
        f"  click 'basic information' in the left sidebar\n"
        f"  scroll to 'app-level tokens'\n"
        f"  click 'generate token and scopes'\n"
        f"  name it anything (e.g. alfard-socket)\n"
        f"  add scope: connections:write → click 'generate'\n"
        f"  copy the token — starts with xapp-[/]"
    )
    webbrowser.open("https://api.slack.com/apps")
    app_token = alfard_input("app-level token (xapp-)", password=True).strip()
    if not app_token or not app_token.startswith("xapp-"):
        console.print(f"  [{p.err}]invalid app token — must start with xapp-[/]")
        return False
    _update_env("SLACK_APP_TOKEN", app_token)
    console.print(f"{dot('ok')} [{p.fg_dim}]app token saved.[/]")

    entry = {"name": name, "transport": "none"}
    data = _load_integrations()
    data.setdefault("servers", [])
    data["servers"] = [s for s in data["servers"] if s["name"] != name]
    data["servers"].append(entry)
    _save_integrations(data)

    console.print(f"\n{dot('ok')} [{p.fg_dim}]slack bot configured.[/]")
    console.print(
        f"\n[{p.fg_faint}]start the bot:[/]\n"
        f"  [{p.fg_em}]alfard slack <agent>[/]"
    )
    if not _already_connected("slack"):
        console.print(
            f"\n[{p.fg_faint}]to also use slack as an mcp tool:[/]\n"
            f"  [{p.fg_em}]alfard connect slack[/]"
        )
    return True


def _connect_apikey(name: str, integration: dict) -> bool:
    console.print(f"\n[{p.fg_em}]{integration['display_name']}[/]")
    console.print(f"[{p.fg_dim}]{integration['description']}[/]\n")

    console.print(f"[{p.fg_dim}]how to get your token:[/]")
    for line in integration["get_token_steps"].splitlines():
        console.print(f"[{p.fg_faint}]{line}[/]")

    url = integration.get("get_token_url", "")
    if url:
        console.print(f"\n[{p.cyan}]{url}[/]")
        webbrowser.open(url)

    token = alfard_input(
        f"{integration['display_name']} token",
        password=True,
    )
    if not token.strip():
        console.print(f"  [{p.err}]no token entered. aborting.[/]")
        return False

    _update_env(integration["credential_env"], token.strip())

    env_key = integration.get("mcp_env_var", integration["credential_env"])
    entry = {
        "name": name,
        "transport": integration["mcp_transport"],
        "command": integration["mcp_command"],
        "args": integration["mcp_args"],
        "env_vars": {env_key: integration["credential_env"]},
        "tools": {
            "reversible": integration["reversible_tools"],
            "irreversible": integration["irreversible_tools"],
        },
    }
    data = _load_integrations()
    data.setdefault("servers", [])
    data["servers"] = [s for s in data["servers"] if s["name"] != name]
    data["servers"].append(entry)
    _save_integrations(data)

    display = integration["display_name"]
    console.print(f"\n{dot('ok')} [{p.fg_dim}]{display} connected.[/]")
    console.print(f"[{p.fg_faint}]run alfard status to confirm.[/]")
    return True


def _connect_oauth(name: str, integration: dict) -> bool:
    console.print(f"\n[{p.fg_em}]{integration['display_name']}[/]")
    console.print(f"[{p.fg_dim}]{integration['description']}[/]\n")

    if not shutil.which("gws"):
        console.print(f"[{p.fg_dim}]installing gws (google workspace cli)...[/]")
        if not shutil.which("npm"):
            console.print(error_block(
                agent="alfard connect",
                state="failed",
                headline="npm is not installed.",
                explanation=f"install node.js from nodejs.org then re-run: alfard connect {name}",
            ))
            return False
        result = subprocess.run(["npm", "install", "-g", "@googleworkspace/cli"])
        if result.returncode != 0:
            console.print(error_block(
                agent="alfard connect",
                state="failed",
                headline="gws installation failed.",
                explanation="run: npm install -g @googleworkspace/cli manually then retry.",
            ))
            return False

    creds_dest = Path.home() / ".config" / "gws" / "client_secret.json"
    if not creds_dest.exists():
        import os as _os
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv()
        ALFARD_CLIENT_ID = _os.environ.get("ALFARD_GOOGLE_CLIENT_ID", "")
        ALFARD_CLIENT_SECRET = _os.environ.get("ALFARD_GOOGLE_CLIENT_SECRET", "")

        if ALFARD_CLIENT_ID and ALFARD_CLIENT_ID != "custom":
            import json as _json
            client_secret_data = {
                "installed": {
                    "client_id": ALFARD_CLIENT_ID,
                    "client_secret": ALFARD_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
            creds_dest.parent.mkdir(parents=True, exist_ok=True)
            creds_dest.write_text(_json.dumps(client_secret_data))
            console.print(f"[{p.fg_dim}]google credentials configured.[/]")
        else:
            console.print(f"[{p.fg_dim}]one-time google setup — about 5 minutes.[/]\n")
            console.print(
                f"[{p.fg_faint}]step 1: create a project\n"
                f"  open google cloud console\n"
                f"  click new project, name it anything (e.g. alfard)\n"
                f"  click create\n\n"
                f"step 2: enable gmail api\n"
                f"  open the gmail api page\n"
                f"  click enable\n\n"
                f"step 3: configure consent screen\n"
                f"  go to apis & services → oauth consent screen\n"
                f"  choose external, fill in app name alfard and your email\n"
                f"  click save through all screens\n"
                f"  click add users and add your gmail address as a test user\n\n"
                f"step 4: create credentials\n"
                f"  go to apis & services → credentials\n"
                f"  click create credentials → oauth client id\n"
                f"  application type: desktop app → name it alfard → create\n"
                f"  click the download button to download the json file[/]"
            )

            alfard_input("press enter to open google cloud console", default="")
            webbrowser.open("https://console.cloud.google.com")
            alfard_input("step 1 done — project created? press enter to continue", default="")

            webbrowser.open("https://console.cloud.google.com/apis/library/gmail.googleapis.com")
            alfard_input("step 2 done — gmail api enabled? press enter to continue", default="")

            webbrowser.open("https://console.cloud.google.com/auth/clients")
            console.print(
                f"\n[{p.fg_dim}]configure the consent screen:[/]\n"
                f"[{p.fg_faint}]  choose external\n"
                f"  fill in app name alfard and your email\n"
                f"  click save through all screens\n"
                f"  click add users and add your gmail address as a test user[/]"
            )
            alfard_input(
                "step 3 done — consent screen configured? press enter to continue",
                default="",
            )

            webbrowser.open("https://console.cloud.google.com/apis/credentials")
            console.print(
                f"\n[{p.fg_dim}]create oauth credentials:[/]\n"
                f"[{p.fg_faint}]  click create credentials → oauth client id\n"
                f"  application type: desktop app → name it alfard → create\n"
                f"  click the download button to download the json file[/]"
            )
            alfard_input("step 4 done — credentials json downloaded? press enter to continue", default="")

            creds_path = alfard_input("credentials json file path").strip().strip("'\"")

            if not creds_path or not Path(creds_path).exists():
                console.print(error_block(
                    agent="alfard connect",
                    state="failed",
                    headline="file not found.",
                    explanation=f"re-run alfard connect {name} and provide a valid path.",
                ))
                return False

            creds_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(creds_path, creds_dest)
            console.print(f"{dot('ok')} [{p.fg_dim}]credentials saved.[/]")

    console.print(f"\n[{p.fg_dim}]opening browser for google sign-in...[/]")
    import os as _os2
    from dotenv import load_dotenv as _load_dotenv2
    _load_dotenv2()
    _env = _os2.environ.copy()
    _client_id = _os2.environ.get("ALFARD_GOOGLE_CLIENT_ID", "")
    _client_secret = _os2.environ.get("ALFARD_GOOGLE_CLIENT_SECRET", "")
    if _client_id:
        _env["GOOGLE_WORKSPACE_CLI_CLIENT_ID"] = _client_id
    if _client_secret:
        _env["GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"] = _client_secret
    result = subprocess.run(["gws", "auth", "login"], env=_env)
    if result.returncode != 0:
        console.print(error_block(
            agent="alfard connect",
            state="failed",
            headline="google sign-in failed.",
            explanation=f"check the error above, then re-run: alfard connect {name}",
        ))
        return False

    console.print(f"[{p.fg_dim}]testing connection...[/]")
    test = subprocess.run(
        ["gws", "gmail", "+triage", "--max", "1"],
        capture_output=True,
        text=True,
    )
    if test.returncode != 0:
        console.print(error_block(
            agent="alfard connect",
            state="failed",
            headline="connection test failed.",
            explanation=test.stderr.strip(),
        ))
        return False

    _update_env(integration["credential_env"], "gws-managed")

    entry = {
        "name": name,
        "transport": integration["mcp_transport"],
        "command": integration["mcp_command"],
        "args": integration["mcp_args"],
        "tools": {
            "reversible": integration["reversible_tools"],
            "irreversible": integration["irreversible_tools"],
        },
    }
    data = _load_integrations()
    data.setdefault("servers", [])
    data["servers"] = [s for s in data["servers"] if s["name"] != name]
    data["servers"].append(entry)
    _save_integrations(data)

    from alfard.agents.loader import list_agents, add_skill, AGENTS_DIR  # noqa: F401

    display = integration["display_name"]
    agents = list_agents()
    added_to: str = ""
    if agents:
        choices = agents + ["all agents"]
        choice = alfard_select(
            f"which agent should get the {display} skill?",
            choices,
            default=agents[0],
        ) or agents[0]

        if choice == "all agents":
            for agent_name in agents:
                add_skill(agent_name, name)
            added_to = "all agents"
        else:
            add_skill(choice, name)
            added_to = choice

    console.print(f"\n{dot('ok')} [{p.fg_dim}]{display} connected.[/]")
    if added_to and added_to.strip():
        console.print(f"[{p.fg_faint}]skill added to: {added_to}[/]")
        console.print(f"\n  [{p.fg_em}]alfard run {added_to.strip()}[/]")
    else:
        console.print(f"\n  [{p.fg_dim}]create an agent first: alfard create[/]")
    return True


def _connect_web_access() -> None:
    """Run the web access wizard for a chosen agent."""
    from alfard.agents.loader import list_agents, AGENTS_DIR
    from alfard.cli.cmd_create import _web_wizard
    agents = list_agents()
    if not agents:
        console.print(f"  [{p.fg_dim}]no agents found. create one first: alfard create[/]")
        return
    agent_name = alfard_select("which agent?", agents, default=agents[0])
    if not agent_name:
        return
    _web_wizard(AGENTS_DIR / agent_name, agent_name)


@click.command(cls=AlfardCommand)
@click.argument("integration", required=False)
def connect(integration: str | None):
    """Connect an external service like Notion, Gmail or GitHub.

    Run without arguments to see available integrations.

    \b
    Examples:
      alfard connect notion
      alfard connect github
      alfard connect gmail
      alfard connect web-access
    """
    if not integration:
        import questionary as _q
        from dotenv import load_dotenv as _ldenv
        from alfard.agents.loader import list_agents, AGENTS_DIR
        from alfard.web.config import WebConfig as _WebConfig
        _ldenv()
        data = _load_integrations()
        connected = {s["name"] for s in data.get("servers", [])}
        if (Path.home() / ".config" / "gws" / "credentials.enc").exists():
            connected.update({"gmail", "gdrive"})
        web_configured = any(
            _WebConfig(AGENTS_DIR / a).enabled for a in list_agents()
        )
        int_choices = [
            _q.Choice(
                title=f"{info['display_name']}{' (connected)' if name in connected else ''}",
                value=name,
                description=info["description"],
            )
            for name, info in CATALOGUE.items()
        ] + [
            _q.Choice(
                title=f"web access{' (configured)' if web_configured else ''}",
                value="web-access",
                description="Configure web search and page fetching for an agent",
            ),
            _q.Choice(title="← back", value="← back"),
        ]
        integration = alfard_select("which integration?", int_choices)
        if not integration or integration == "← back":
            return

    integration = integration.lower().strip()

    if integration in ("web access", "web-access"):
        _connect_web_access()
        return

    if integration not in CATALOGUE:
        console.print(error_block(
            agent="alfard connect",
            state="failed",
            headline=f"unknown integration: '{integration}'",
            explanation="run alfard connect to see available integrations.",
        ))
        raise SystemExit(1)

    info = CATALOGUE[integration]

    if _already_connected(integration):
        if not alfard_confirm(
            f"{info['display_name']} is already connected. reconnect?",
            default=False,
        ):
            return

    if integration == "slack":
        _connect_slack(integration, info)
    elif integration == "slack-bot":
        _connect_slack_bot(integration, info)
    elif info["auth"] == AUTH_APIKEY:
        _connect_apikey(integration, info)
    else:
        _connect_oauth(integration, info)
