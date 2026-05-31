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
from alfard.paths import ALFARD_HOME, load_env

_ENV_PATH = ALFARD_HOME / ".env"
_INTEGRATIONS_PATH = ALFARD_HOME / "config" / "integrations.yaml"


def _refresh_lazy_tool_catalog() -> None:
    """Silently rebuild the lazy-tool catalog when it is already installed."""
    from alfard.integrations.lazy_tool import lazy_tool_is_available, update_lazy_tool_catalog
    if not lazy_tool_is_available():
        return
    if update_lazy_tool_catalog():
        console.print(f"{dot('ok')} [{p.fg_dim}]lazy-tool catalog updated — mcp schemas will load on demand.[/]")


def _update_env(key: str, value: str) -> None:
    lines: list[str] = []
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()

    pattern = re.compile(rf"^{re.escape(key)}\s*=")
    updated = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        lines.append(f"{key}={value}")

    _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _ENV_PATH.chmod(0o600)


def _load_integrations() -> dict:
    if not _INTEGRATIONS_PATH.exists():
        return {"servers": []}
    raw = _INTEGRATIONS_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not data:
        return {"servers": []}
    return data


def _save_integrations(data: dict) -> None:
    _INTEGRATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _INTEGRATIONS_PATH.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")


def _already_connected(name: str) -> bool:
    data = _load_integrations()
    return any(s["name"] == name for s in data.get("servers", []))


def _is_headless() -> bool:
    """Return True when running on a server with no browser available."""
    if sys.platform == "linux":
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return True
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return True
    return False


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
        elif sys.platform == "win32":
            result = subprocess.run(
                ["clip"],
                input=text.encode("utf-8"),
                capture_output=True,
            )
            return result.returncode == 0
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
    load_env()
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


def _write_slack_cfg(channel: str) -> None:
    config_path = ALFARD_HOME / "config" / "alfard.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
    config.setdefault("slack", {})
    config["slack"]["channel"] = channel
    config["slack"]["bot_token_env"] = "SLACK_BOT_TOKEN"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


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

    channel_name = alfard_input(
        "slack channel for cron approval notifications",
        hint="channel where alfard will post approval requests (e.g. #approvals)",
        default="#approvals",
    ).strip() or "#approvals"
    _write_slack_cfg(channel_name)
    console.print(f"{dot('ok')} [{p.fg_dim}]approval channel saved.[/]")

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
        f"\n[{p.fg_faint}]to also use as a chat bot:[/]\n"
        f"  [{p.fg_em}]alfard channel connect slack[/]"
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

    if integration.get("routed_via_lazy_tool"):
        _refresh_lazy_tool_catalog()

    display = integration["display_name"]
    _, added_to = _ask_agent_assignment(display)

    console.print(f"\n{dot('ok')} [{p.fg_dim}]{display} connected.[/]")
    if added_to and added_to.strip():
        console.print(f"[{p.fg_faint}]skill added to: {added_to.strip()}[/]")
    else:
        console.print(f"  [{p.fg_dim}]create an agent first: alfard create[/]")
    return True


def _install_gogcli() -> bool:
    from alfard.setup.dependencies import install_gogcli
    return install_gogcli()


def _copy_to_terminal_clipboard(text: str) -> bool:
    """Push text to the user's local clipboard via OSC 52 escape sequence.
    Works over SSH if the terminal supports it (iTerm2, Kitty, WezTerm)."""
    import base64
    try:
        encoded = base64.b64encode(text.encode()).decode()
        sys.stdout.write(f"\033]52;c;{encoded}\007")
        sys.stdout.flush()
        return True
    except Exception:
        return False


def _gog_env() -> dict:
    from alfard.security.keystore import get_or_create_gog_password
    env = os.environ.copy()
    env["GOG_HOME"] = str(ALFARD_HOME / "gog")
    env["GOG_KEYRING_BACKEND"] = "file"
    env["GOG_KEYRING_PASSWORD"] = get_or_create_gog_password()
    return env


def _connect_oauth(name: str, integration: dict) -> bool:
    import json as _json
    import tempfile as _tempfile

    console.print(f"\n[{p.fg_em}]{integration['display_name']}[/]")
    console.print(f"[{p.fg_dim}]{integration['description']}[/]\n")

    headless = _is_headless()

    # Install check — offer to auto-install
    if not shutil.which("gog"):
        console.print(f"[{p.fg_dim}]gogcli is required for Gmail.[/]")
        if not alfard_confirm("install gogcli?", default=True):
            return False
        _install_gogcli()
        if not shutil.which("gog"):
            console.print(f"[{p.err}]installed but gog not found on PATH.[/]")
            console.print(f"[{p.fg_faint}]open a new terminal and re-run: alfard connect {name}[/]")
            return False

    # Credentials check
    creds_file = ALFARD_HOME / "gog" / "credentials"
    _skip_creds = False
    if creds_file.exists():
        _skip_creds = alfard_confirm("google credentials already saved — use existing?", default=True)

    if not _skip_creds:
        # Always ask whether user needs the GCP setup walkthrough
        already_setup = alfard_confirm(
            "have you already set up a google cloud project for alfard?",
            default=False,
        )

        if already_setup:
            console.print(f"[{p.fg_dim}]skipping gcp setup — jumping straight to credentials.[/]\n")
        else:
            # Full GCP wizard — steps 1-3
            console.print(f"\n[{p.fg_dim}]one-time google setup — about 5 minutes.[/]\n")

            console.print(f"[{p.fg_em}]step 1 — create a project[/]")
            console.print(
                f"[{p.fg_faint}]  open google cloud console\n"
                f"  click new project, name it anything (e.g. alfard)\n"
                f"  click create[/]"
            )
            if headless:
                console.print(f"  [{p.fg_faint}]open: https://console.cloud.google.com[/]")
            else:
                webbrowser.open("https://console.cloud.google.com")
            alfard_input("step 1 done — project created? press enter to continue", default="")

            console.print(f"\n[{p.fg_em}]step 2 — enable gmail api[/]")
            if headless:
                console.print(f"  [{p.fg_faint}]open: https://console.cloud.google.com/apis/library/gmail.googleapis.com[/]")
            else:
                webbrowser.open("https://console.cloud.google.com/apis/library/gmail.googleapis.com")
            alfard_input("step 2 done — gmail api enabled? press enter to continue", default="")

            console.print(f"\n[{p.fg_em}]step 3 — configure consent screen[/]")
            console.print(
                f"[{p.fg_faint}]  choose external\n"
                f"  fill in app name alfard and your email\n"
                f"  click save through all screens\n"
                f"  click add users and add your gmail address as a test user[/]"
            )
            if headless:
                console.print(f"  [{p.fg_faint}]open: https://console.cloud.google.com/auth/clients[/]")
            else:
                webbrowser.open("https://console.cloud.google.com/auth/clients")
            alfard_input("step 3 done — consent screen configured? press enter to continue", default="")

            console.print(f"\n[{p.fg_em}]step 4 — create credentials[/]")
            console.print(
                f"[{p.fg_faint}]  go to apis & services → credentials\n"
                f"  click create credentials → oauth client id\n"
                f"  application type: desktop app → name it alfard → create\n"
                f"  don't click download — just copy the two values shown[/]"
            )
            if headless:
                console.print(f"  [{p.fg_faint}]open: https://console.cloud.google.com/apis/credentials[/]")
            else:
                webbrowser.open("https://console.cloud.google.com/apis/credentials")
            alfard_input("step 4 done — credentials created? press enter to continue", default="")

        client_id = alfard_input("client id (ends in .apps.googleusercontent.com)").strip()
        if not client_id.endswith(".apps.googleusercontent.com"):
            console.print(f"\n  [{p.err}]invalid client id — must end with .apps.googleusercontent.com[/]")
            return False
        client_secret = alfard_input("client secret", password=True).strip()

        creds_data = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        with _tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            _json.dump(creds_data, tf)
            tmppath = tf.name
        try:
            result = subprocess.run(["gog", "auth", "credentials", tmppath], env=_gog_env())
        finally:
            Path(tmppath).unlink(missing_ok=True)
        if result.returncode != 0:
            console.print(f"[{p.err}]failed to save credentials.[/]")
            return False
        console.print(f"{dot('ok')} [{p.fg_dim}]credentials saved.[/]")

    # Publish step — removes the 7-day token limit
    console.print(
        f"\n[{p.fg_em}]one more step — open oauth consent screen → click 'publish app'[/]\n"
        f"[{p.fg_faint}]this removes the 7-day token limit. your app stays private.[/]"
    )
    if headless:
        console.print(f"  [{p.fg_faint}]open: https://console.cloud.google.com/auth/clients[/]")
    else:
        webbrowser.open("https://console.cloud.google.com/auth/clients")
    alfard_input("press enter once published", default="")

    # Gmail address
    email = alfard_input("your gmail address").strip()

    # Auth flow
    if headless:
        step1 = subprocess.run(
            ["gog", "auth", "add", email, "--services", "gmail,drive",
             "--remote", "--step", "1"],
            env=_gog_env(),
            capture_output=True,
            text=True,
        )
        auth_url_to_open = step1.stdout.strip()

        console.print("")
        console.print(f"[{p.fg_em}]open this url in your browser to sign in:[/]")
        console.print("")
        print(auth_url_to_open)
        console.print("")

        copied = _copy_to_terminal_clipboard(auth_url_to_open)
        if copied:
            console.print(f"{dot('ok')} [{p.fg_dim}]url copied to clipboard[/]")
        else:
            console.print(f"[{p.fg_faint}](select and copy the url above)[/]")

        auth_url = alfard_input("paste the redirect url after signing in").strip()
        result2 = subprocess.run(
            ["gog", "auth", "add", email, "--services", "gmail,drive",
             "--remote", "--step", "2", "--auth-url", auth_url],
            env=_gog_env(),
        )
        if result2.returncode != 0:
            console.print(error_block(
                agent="alfard connect",
                state="failed",
                headline="google sign-in failed.",
                explanation=f"check the error above, then re-run: alfard connect {name}",
            ))
            return False
    else:
        console.print(f"\n[{p.fg_dim}]opening browser for google sign-in...[/]")
        result = subprocess.run(
            ["gog", "auth", "add", email, "--services", "gmail,drive"],
            env=_gog_env(),
        )
        if result.returncode != 0:
            console.print(error_block(
                agent="alfard connect",
                state="failed",
                headline="google sign-in failed.",
                explanation=f"check the error above, then re-run: alfard connect {name}",
            ))
            return False

    # Connection test
    console.print(f"[{p.fg_dim}]testing connection...[/]")
    test = subprocess.run(
        ["gog", "gmail", "search", "newer_than:1d", "--max", "1", "--json"],
        capture_output=True,
        text=True,
        env=_gog_env(),
    )
    if test.returncode != 0:
        console.print(error_block(
            agent="alfard connect",
            state="failed",
            headline="connection test failed.",
            explanation=test.stderr.strip(),
        ))
        return False

    _update_env("GOG_ACCOUNT", email)

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

    if integration.get("routed_via_lazy_tool"):
        _refresh_lazy_tool_catalog()

    display = integration["display_name"]
    _, added_to = _ask_agent_assignment(display)

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
        from alfard.agents.loader import list_agents, AGENTS_DIR
        from alfard.web.config import WebConfig as _WebConfig
        load_env()
        data = _load_integrations()
        connected = {s["name"] for s in data.get("servers", [])}
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
        return

    info = CATALOGUE[integration]

    if _already_connected(integration):
        if not alfard_confirm(
            f"{info['display_name']} is already connected. reconnect?",
            default=False,
        ):
            return

    if integration == "slack":
        _connect_slack(integration, info)
    elif info["auth"] == AUTH_APIKEY:
        _connect_apikey(integration, info)
    else:
        _connect_oauth(integration, info)
