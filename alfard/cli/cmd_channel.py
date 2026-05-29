"""Manage chat channels — connect and disconnect Slack, Telegram, Discord, etc."""

import os
import re

import click
from alfard.cli.help_formatter import AlfardCommand, AlfardGroup
from alfard.cli.theme import p, console
from alfard.cli.components import dot, error_block, alfard_select, alfard_confirm
from alfard.paths import ALFARD_HOME, load_env

_ENV_PATH = ALFARD_HOME / ".env"

# Registry of supported channels.
_CHANNELS: dict[str, dict] = {
    "slack": {
        "display_name": "Slack",
        "description": "Chat with your agent via Slack DMs and @mentions (Socket Mode)",
        "env_keys": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
        "integrations_name": "slack-bot",
    },
    "telegram": {
        "display_name": "Telegram",
        "description": "Chat with your agent via a Telegram bot (long polling)",
        "env_keys": ["TELEGRAM_BOT_TOKEN"],
        "integrations_name": "telegram-bot",
    },
    "discord": {
        "display_name": "Discord",
        "description": "Chat with your agent via a Discord bot (gateway)",
        "env_keys": ["DISCORD_BOT_TOKEN"],
        "integrations_name": "discord-bot",
    },
}


def connected_channels() -> list[str]:
    """Return names of channels that have all required tokens set."""
    load_env()
    return [
        name for name, info in _CHANNELS.items()
        if all(os.environ.get(k) for k in info["env_keys"])
    ]


def _remove_env_keys(keys: list[str]) -> None:
    """Remove a set of keys from the plain .env file."""
    if not _ENV_PATH.exists():
        return
    content = _ENV_PATH.read_text(encoding="utf-8")
    for key in keys:
        content = re.sub(rf"^{re.escape(key)}=.*$\n?", "", content, flags=re.MULTILINE)
    _ENV_PATH.write_text(content, encoding="utf-8")
    _ENV_PATH.chmod(0o600)


def _remove_from_integrations(entry_name: str) -> None:
    import yaml
    integrations_path = ALFARD_HOME / "config" / "integrations.yaml"
    if not integrations_path.exists():
        return
    with open(integrations_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {"servers": []}
    data["servers"] = [s for s in data.get("servers", []) if s.get("name") != entry_name]
    with open(integrations_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


@click.group(cls=AlfardGroup)
def channel() -> None:
    """Connect and disconnect chat channels (Slack, Telegram, Discord)."""


@channel.command(cls=AlfardCommand, name="connect")
@click.argument("name", required=False)
def connect(name: str | None) -> None:
    """Connect a chat channel so your agent can receive messages.

    \b
    Examples:
      alfard channel connect
      alfard channel connect slack
      alfard channel connect telegram
    """
    load_env()

    import questionary as _q
    available = list(_CHANNELS.keys())

    if not name:
        choices = [
            _q.Choice(
                title=(
                    f"{info['display_name']}"
                    f"  {'(connected)' if n in connected_channels() else ''}"
                ).rstrip(),
                value=n,
                description=info["description"],
            )
            for n, info in _CHANNELS.items()
        ] + [_q.Choice(title="← back", value="← back")]
        name = alfard_select("which channel?", choices)
        if not name or name == "← back":
            return

    name = name.lower().strip()

    if name not in _CHANNELS:
        console.print(error_block(
            agent="alfard channel connect",
            state="failed",
            headline=f"unknown channel: '{name}'",
            explanation=f"available: {', '.join(available)}",
        ))
        raise SystemExit(1)

    if name == "slack":
        _connect_slack()
    elif name == "telegram":
        _connect_telegram()
    elif name == "discord":
        _connect_discord()


def _connect_slack() -> None:
    from alfard.cli.cmd_connect import _ensure_slack_bot_token, _update_env, _derive_team_id
    import webbrowser

    info = _CHANNELS["slack"]
    console.print(f"\n[{p.fg_em}]{info['display_name']}[/]")
    console.print(f"[{p.fg_dim}]{info['description']}[/]\n")

    bot_token = _ensure_slack_bot_token()
    if not bot_token:
        console.print(f"\n[{p.err}]slack not connected.[/]")
        return

    console.print(f"[{p.fg_dim}]verifying token...[/]")
    team_id = _derive_team_id(bot_token)
    if not team_id:
        console.print(f"  [{p.err}]could not verify token — check it and try again.[/]")
        return
    _update_env("SLACK_TEAM_ID", team_id)
    console.print(f"{dot('ok')} [{p.fg_dim}]workspace verified.[/]")

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
    from alfard.cli.components import alfard_input
    webbrowser.open("https://api.slack.com/apps")
    app_token = alfard_input("app-level token (xapp-)", password=True).strip()
    if not app_token or not app_token.startswith("xapp-"):
        console.print(f"  [{p.err}]invalid app token — must start with xapp-[/]")
        return
    _update_env("SLACK_APP_TOKEN", app_token)
    console.print(f"{dot('ok')} [{p.fg_dim}]app token saved.[/]")

    # Record in integrations.yaml so it survives restarts
    import yaml
    integrations_path = ALFARD_HOME / "config" / "integrations.yaml"
    integrations_path.parent.mkdir(parents=True, exist_ok=True)
    if integrations_path.exists():
        with open(integrations_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"servers": []}
    else:
        data = {"servers": []}
    data.setdefault("servers", [])
    data["servers"] = [s for s in data["servers"] if s.get("name") != "slack-bot"]
    data["servers"].append({"name": "slack-bot", "transport": "none"})
    with open(integrations_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    console.print(f"\n{dot('ok')} [{p.fg_dim}]slack channel connected.[/]")
    console.print(
        f"[{p.fg_faint}]run [/][{p.fg_em}]alfard run <agent>[/]"
        f"[{p.fg_faint}] to start — slack will be active alongside the terminal.[/]"
    )
    console.print(
        f"[{p.fg_faint}]or run [/][{p.fg_em}]alfard headless <agent>[/]"
        f"[{p.fg_faint}] to run with no terminal.[/]"
    )


def _connect_telegram() -> None:
    from alfard.cli.cmd_connect import _update_env
    from alfard.cli.components import alfard_input

    info = _CHANNELS["telegram"]
    console.print(f"\n[{p.fg_em}]{info['display_name']}[/]")
    console.print(f"[{p.fg_dim}]{info['description']}[/]\n")

    console.print(
        f"[{p.fg_faint}]  1. Open Telegram and search for @BotFather\n"
        f"  2. Send /newbot and follow the prompts\n"
        f"  3. Copy the token BotFather gives you[/]\n"
    )

    bot_token = alfard_input("bot token", password=True).strip()
    if not bot_token:
        console.print(f"[{p.err}]no token entered — telegram not connected.[/]")
        return
    _update_env("TELEGRAM_BOT_TOKEN", bot_token)
    console.print(f"{dot('ok')} [{p.fg_dim}]bot token saved.[/]")

    console.print(
        f"\n[{p.fg_faint}]  Allowed user IDs restrict who can talk to your bot.\n"
        f"  Find your Telegram user ID by messaging @userinfobot.\n"
        f"  Enter comma-separated IDs, or leave blank to allow everyone.[/]\n"
    )
    allowed = alfard_input("allowed user IDs (optional, comma-separated)").strip()
    if allowed:
        _update_env("TELEGRAM_ALLOWED_USERS", allowed)
        console.print(f"{dot('ok')} [{p.fg_dim}]allowed users saved.[/]")
    else:
        console.print(
            f"[{p.warn}]  ⚠  No allowed users set. "
            f"Anyone who finds your bot can message it.[/]"
        )

    import yaml
    integrations_path = ALFARD_HOME / "config" / "integrations.yaml"
    integrations_path.parent.mkdir(parents=True, exist_ok=True)
    if integrations_path.exists():
        with open(integrations_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"servers": []}
    else:
        data = {"servers": []}
    data.setdefault("servers", [])
    data["servers"] = [s for s in data["servers"] if s.get("name") != "telegram-bot"]
    data["servers"].append({"name": "telegram-bot", "transport": "none"})
    with open(integrations_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    console.print(f"\n{dot('ok')} [{p.fg_dim}]telegram channel connected.[/]")
    console.print(
        f"[{p.fg_faint}]run [/][{p.fg_em}]alfard run <agent>[/]"
        f"[{p.fg_faint}] to start — telegram will be active alongside the terminal.[/]"
    )
    console.print(
        f"[{p.fg_faint}]or run [/][{p.fg_em}]alfard headless <agent>[/]"
        f"[{p.fg_faint}] to run with no terminal.[/]"
    )


def _connect_discord() -> None:
    from alfard.cli.cmd_connect import _update_env
    from alfard.cli.components import alfard_input

    info = _CHANNELS["discord"]
    console.print(f"\n[{p.fg_em}]{info['display_name']}[/]")
    console.print(f"[{p.fg_dim}]{info['description']}[/]\n")

    console.print(
        f"[{p.fg_faint}]  1. Go to discord.com/developers/applications → your app → Bot\n"
        f"  2. Scroll to 'Privileged Gateway Intents', enable Message Content Intent, save\n"
        f"  3. Scroll up, click Reset Token, copy it[/]\n"
    )

    bot_token = alfard_input("bot token", password=True).strip()
    if not bot_token:
        console.print(f"[{p.err}]no token entered — discord not connected.[/]")
        return
    _update_env("DISCORD_BOT_TOKEN", bot_token)
    console.print(f"{dot('ok')} [{p.fg_dim}]bot token saved.[/]")

    console.print(
        f"\n[{p.fg_faint}]Now add the bot to your server:\n"
        f"  1. Go to OAuth2 in the left sidebar\n"
        f"  2. Under Scopes: check 'bot'\n"
        f"  3. Scroll down, under Bot Permissions check:\n"
        f"     Send Messages, Read Message History, Add Reactions, View Channels\n"
        f"  4. Copy the Generated URL at the bottom of the page\n"
        f"  5. Open it in your browser, select your server, click Authorise[/]\n"
    )

    console.print(
        f"[{p.fg_faint}]  Allowed guild IDs restrict which servers the bot responds in.\n"
        f"  Right-click a server icon in Discord (with Developer Mode on) to copy its ID.\n"
        f"  Enter comma-separated IDs, or leave blank to allow all servers.[/]\n"
    )
    allowed = alfard_input("allowed guild IDs (optional, comma-separated)").strip()
    if allowed:
        _update_env("DISCORD_ALLOWED_GUILDS", allowed)
        console.print(f"{dot('ok')} [{p.fg_dim}]allowed guilds saved.[/]")
    else:
        console.print(
            f"[{p.warn}]  ⚠  No guilds set. "
            f"Bot will respond in any server it is added to.[/]"
        )

    import yaml
    integrations_path = ALFARD_HOME / "config" / "integrations.yaml"
    integrations_path.parent.mkdir(parents=True, exist_ok=True)
    if integrations_path.exists():
        with open(integrations_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"servers": []}
    else:
        data = {"servers": []}
    data.setdefault("servers", [])
    data["servers"] = [s for s in data["servers"] if s.get("name") != "discord-bot"]
    data["servers"].append({"name": "discord-bot", "transport": "none"})
    with open(integrations_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    console.print(f"\n{dot('ok')} [{p.fg_dim}]discord channel connected.[/]")
    console.print(
        f"[{p.fg_faint}]run [/][{p.fg_em}]alfard run <agent>[/]"
        f"[{p.fg_faint}] to start — discord will be active alongside the terminal.[/]"
    )
    console.print(
        f"[{p.fg_faint}]or run [/][{p.fg_em}]alfard headless <agent>[/]"
        f"[{p.fg_faint}] to run with no terminal.[/]"
    )


@channel.command(cls=AlfardCommand, name="disconnect")
@click.argument("name", required=False)
def disconnect(name: str | None) -> None:
    """Disconnect a chat channel and remove its credentials.

    \b
    Examples:
      alfard channel disconnect
      alfard channel disconnect slack
    """
    load_env()

    active = connected_channels()

    if not name:
        if not active:
            console.print(f"[{p.fg_faint}]no channels connected.[/]")
            console.print(
                f"[{p.fg_dim}]connect one with: [/][{p.fg_em}]alfard channel connect[/]"
            )
            return
        name = alfard_select("which channel to disconnect?", active)
        if not name:
            return

    name = name.lower().strip()

    if name not in _CHANNELS:
        console.print(error_block(
            agent="alfard channel disconnect",
            state="failed",
            headline=f"unknown channel: '{name}'",
            explanation=f"available: {', '.join(_CHANNELS)}",
        ))
        raise SystemExit(1)

    info = _CHANNELS[name]

    console.print(f"\n{dot('warn')} [{p.warn}]{info['display_name']}[/]")
    if not alfard_confirm("disconnect? this removes all stored tokens.", default=False):
        console.print(f"[{p.fg_dim}]cancelled.[/]")
        return

    _remove_env_keys(info["env_keys"])
    _remove_from_integrations(info["integrations_name"])

    console.print(f"\n{dot('ok')} [{p.fg_em}]{info['display_name']}[/] [{p.fg_dim}]disconnected.[/]")
