"""CLI commands for managing agent folder mounts."""

import click
import yaml
from pathlib import Path
from alfard.cli.theme import p, c, console
from alfard.cli.components import dot, error_block, alfard_table, alfard_select, alfard_input, alfard_confirm
from alfard.agents.loader import list_agents, AGENTS_DIR

MOUNTS_FILE = "mounts.yaml"


def _load_mounts(agent_name: str) -> dict:
    path = AGENTS_DIR / agent_name / MOUNTS_FILE
    if not path.exists():
        return {"mounts": []}
    with open(path) as f:
        return yaml.safe_load(f) or {"mounts": []}


def _save_mounts(agent_name: str, data: dict) -> None:
    path = AGENTS_DIR / agent_name / MOUNTS_FILE
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


@click.group(invoke_without_command=True)
@click.pass_context
def mount(ctx: click.Context):
    """Manage folder mounts for agents.

    Mounts give agents access to specific folders on your machine.
    All file operations are restricted to declared paths.

    \b
    Examples:
      alfard mount add postman ~/Documents/work --access readwrite
      alfard mount add postman ~/Desktop/Projects/Stocky --access readonly
      alfard mount list postman
      alfard mount remove postman ~/Documents/work
    """
    if ctx.invoked_subcommand is not None:
        return

    import questionary

    while True:
        console.clear()
        console.print(f"\n[{p.fg_em}]manage mounts[/]\n")
        action = alfard_select("what would you like to do?", [
            "list mounts",
            "add a mount",
            "remove a mount",
            questionary.Separator(),
            "← back",
        ])
        if not action or action == "← back":
            return

        if action == "list mounts":
            ctx.invoke(list_mounts)
        elif action == "add a mount":
            agents = list_agents()
            if not agents:
                console.print(f"[{p.err}]no agents found. run alfard create first.[/]")
                continue
            agent = agents[0] if len(agents) == 1 else alfard_select("which agent?", agents)
            if not agent:
                continue
            path = alfard_input("folder path", hint="e.g. ~/Documents/work").strip()
            if not path:
                continue
            access = alfard_select("access level?", ["readonly", "readwrite"], default="readonly")
            if not access:
                continue
            ctx.invoke(add, agent=agent, path=path, access=access)
        elif action == "remove a mount":
            agents = list_agents()
            if not agents:
                console.print(f"[{p.err}]no agents found.[/]")
                continue
            agent = agents[0] if len(agents) == 1 else alfard_select("which agent?", agents)
            if not agent:
                continue
            data = _load_mounts(agent)
            mounts = [m["path"] for m in data.get("mounts", [])]
            if not mounts:
                console.print(f"[{p.fg_faint}]{agent} has no mounts.[/]")
                continue
            path = alfard_select("which mount to remove?", mounts)
            if not path:
                continue
            ctx.invoke(remove, agent=agent, path=path)
        alfard_input("press enter to continue", default="")


@mount.command(name="add")
@click.argument("agent", required=False)
@click.argument("path", required=False)
@click.option("--access", "-a",
              type=click.Choice(["readonly", "readwrite"]),
              default="readonly",
              help="Access level: readonly or readwrite (default: readonly)")
def add(agent: str | None, path: str | None, access: str):
    """Mount a folder for an agent."""
    if not agent:
        agents = list_agents()
        if not agents:
            console.print(f"[{p.err}]no agents found. run alfard create first.[/]")
            raise SystemExit(1)
        agent = alfard_select("which agent?", agents)
        if not agent:
            return
    if agent not in list_agents():
        console.print(error_block(
            agent="alfard mount",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)

    if not path:
        path = alfard_input("folder path", hint="e.g. ~/Documents/work").strip()
        if not path:
            return

    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        console.print(error_block(
            agent="alfard mount",
            state="failed",
            headline=f"path does not exist: {path}",
            explanation=f"create the folder first: mkdir -p {resolved}",
        ))
        raise SystemExit(1)

    if not resolved.is_dir():
        console.print(error_block(
            agent="alfard mount",
            state="failed",
            headline=f"path is not a directory: {path}",
            explanation="",
        ))
        raise SystemExit(1)

    data = _load_mounts(agent)
    stored_path = str(Path(path).expanduser())
    existing_paths = [m["path"] for m in data.get("mounts", [])]

    if stored_path in existing_paths:
        console.print(f"  [{p.warn}]already mounted: {path}[/]")
        raise SystemExit(1)

    data.setdefault("mounts", []).append({
        "path": stored_path,
        "access": access,
    })
    _save_mounts(agent, data)

    access_label = "read+write" if access == "readwrite" else "read only"
    console.print(f"\n{dot('ok')} [{p.fg_dim}]mount added.[/]\n")
    console.print(f"  [{p.fg_faint}]{'agent':<8}[/] [{p.fg_em}]{agent}[/]")
    console.print(f"  [{p.fg_faint}]{'path':<8}[/] [{p.fg_em}]{resolved}[/]")
    console.print(f"  [{p.fg_faint}]{'access':<8}[/] [{p.fg_dim}]{access_label}[/]")
    console.print(f"\n[{p.fg_faint}]the agent can now access files in this folder.[/]")


@mount.command(name="remove")
@click.argument("agent", required=False)
@click.argument("path", required=False)
def remove(agent: str | None, path: str | None):
    """Remove a folder mount from an agent."""
    if not agent:
        agents = list_agents()
        if not agents:
            console.print(f"[{p.err}]no agents found.[/]")
            raise SystemExit(1)
        agent = alfard_select("which agent?", agents)
        if not agent:
            return
    if agent not in list_agents():
        console.print(error_block(
            agent="alfard mount",
            state="failed",
            headline=f"agent '{agent}' not found.",
            explanation="",
        ))
        raise SystemExit(1)

    if not path:
        data = _load_mounts(agent)
        mounts = [m["path"] for m in data.get("mounts", [])]
        if not mounts:
            console.print(f"[{p.fg_faint}]{agent} has no mounts.[/]")
            return
        path = alfard_select("which mount to remove?", mounts)
        if not path:
            return

    stored_path = str(Path(path).expanduser())
    data = _load_mounts(agent)
    original = len(data.get("mounts", []))
    data["mounts"] = [
        m for m in data.get("mounts", [])
        if m["path"] != stored_path
    ]

    if len(data["mounts"]) == original:
        console.print(f"  [{p.warn}]mount not found: {path}[/]")
        raise SystemExit(1)

    _save_mounts(agent, data)
    console.print(f"{dot('ok')} [{p.fg_dim}]removed mount: {path}[/]")


@mount.command(name="list")
@click.argument("agent", required=False)
def list_mounts(agent: str | None):
    """List folder mounts for an agent or all agents."""
    agents = [agent] if agent else list_agents()
    any_mounts = False

    for a in agents:
        data = _load_mounts(a)
        mounts = data.get("mounts", [])
        if not mounts:
            continue
        any_mounts = True

        rows = []
        for m in mounts:
            mount_path = Path(m["path"]).expanduser()
            exists_str = (
                c("ok", "ok") if mount_path.exists() else c("err", "missing")
            )
            access = m.get("access", "readonly")
            access_str = (
                c("ok", "read+write") if access == "readwrite" else c("fg_dim", "read only")
            )
            rows.append({
                "path": m["path"],
                "access": access_str,
                "exists": exists_str,
            })

        console.print(f"\n[{p.fg_dim}]mounts — {a}[/]")
        console.print(alfard_table(
            [
                {"header": "path", "key": "path"},
                {"header": "access", "key": "access"},
                {"header": "exists", "key": "exists"},
            ],
            rows,
        ))

    if not any_mounts:
        console.print(
            f"[{p.fg_dim}]no mounts configured.[/]\n"
            f"[{p.fg_faint}]add one: alfard mount add <agent> <path>[/]"
        )
