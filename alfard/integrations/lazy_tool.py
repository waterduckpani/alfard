"""lazy-tool integration — installs, configures, and manages the lazy-tool MCP proxy.

lazy-tool is a search-mode MCP proxy that keeps only meta-tools in the LLM context
and loads full tool schemas on demand, dramatically reducing input token counts.
"""

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

import yaml

from alfard.paths import ALFARD_HOME, load_env

LAZY_TOOL_CONFIG = ALFARD_HOME / "lazy-tool" / "config.yaml"

_INSTALL_DIR = Path.home() / ".local" / "bin"
_FALLBACK_VERSION = "1.0.2"

# Hardcoded SHA256 checksums for v1.0.2 — used when checksums.txt is unreachable.
_V102_CHECKSUMS: dict[str, str] = {
    "linux_amd64":  "585a0881c02b62c9dc792142108fa1951b77682303c3a6d339fcbcd066514e7d",
    "linux_arm64":  "c2de0ac812e6b03438ef2e881aff5414fbbea0acef98798eb5d858961201177c",
    "darwin_amd64": "ee2577e9bf2fd8a3ca6467fa07446e0c48b0448b5a9519359c8f9b994650c947",
    "darwin_arm64": "597a6427a48452a291e7b484baf4105161a79664dd2eb4eb3462a716217014de",
}

_ARCH_MAP: dict[str, str] = {
    "x86_64": "amd64", "AMD64": "amd64",
    "aarch64": "arm64", "arm64": "arm64",
}


def lazy_tool_is_available() -> bool:
    """Return True when lazy-tool is on PATH and its config exists."""
    return shutil.which("lazy-tool") is not None and LAZY_TOOL_CONFIG.exists()


# ── Installation ────────────────────────────────────────────────────────────


def _fetch_latest_version() -> str:
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/mcp-shark/lazy-tool/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())["tag_name"].lstrip("v")
    except Exception:
        return _FALLBACK_VERSION


def _verify_checksum(file_path: Path, expected: str) -> bool:
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest() == expected


def _fetch_remote_checksum(version: str, filename: str) -> str | None:
    """Download checksums.txt and return the SHA256 for filename, or None."""
    url = (
        f"https://github.com/mcp-shark/lazy-tool/releases/download/"
        f"v{version}/checksums.txt"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            for line in r.read().decode("utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == filename:
                    return parts[0]
    except Exception:
        pass
    return None


def _install_lazy_tool() -> bool:
    system = platform.system().lower()
    lt_arch = _ARCH_MAP.get(platform.machine())

    if not lt_arch:
        print(f"  unsupported architecture: {platform.machine()}")
        return False

    if system == "windows":
        print("  auto-install not supported on windows.")
        print("  download from: https://github.com/mcp-shark/lazy-tool/releases")
        return False

    if system not in ("darwin", "linux"):
        print(f"  unsupported platform: {system}")
        return False

    version = _fetch_latest_version()
    platform_key = f"{system}_{lt_arch}"
    filename = f"lazy-tool_{version}_{system}_{lt_arch}.tar.gz"
    url = (
        f"https://github.com/mcp-shark/lazy-tool/releases/download/"
        f"v{version}/{filename}"
    )
    tmp = Path(f"/tmp/lazy-tool_{version}.tar.gz")

    print(f"  downloading lazy-tool v{version}...")
    try:
        urllib.request.urlretrieve(url, tmp)
    except Exception as exc:
        print(f"  download failed: {exc}")
        return False

    # Prefer remote checksums.txt; fall back to hardcoded v1.0.2 values.
    expected = _fetch_remote_checksum(version, filename)
    if expected is None and version == _FALLBACK_VERSION:
        expected = _V102_CHECKSUMS.get(platform_key)

    if expected:
        if not _verify_checksum(tmp, expected):
            tmp.unlink(missing_ok=True)
            print("  checksum mismatch — aborting. file may be corrupt or tampered.")
            return False
    else:
        print("  warning: could not verify checksum — proceeding.")

    _INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    dest = _INSTALL_DIR / "lazy-tool"

    try:
        with tarfile.open(tmp) as tar:
            member = next(
                m for m in tar.getmembers()
                if m.name.endswith("lazy-tool") and not m.isdir()
            )
            member.name = "lazy-tool"
            tar.extract(member, path=_INSTALL_DIR)
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        tmp.unlink(missing_ok=True)
    except Exception as exc:
        print(f"  extract failed: {exc}")
        tmp.unlink(missing_ok=True)
        return False

    os.environ["PATH"] = f"{_INSTALL_DIR}:{os.environ.get('PATH', '')}"
    print(f"  lazy-tool installed to {dest}")
    if system == "linux":
        print(
            "  add to your shell permanently:\n"
            "    echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.bashrc"
        )
    return True


def ensure_lazy_tool() -> bool:
    """Check lazy-tool is installed, install if missing. Returns True if ready."""
    if shutil.which("lazy-tool"):
        return True

    print("lazy-tool is required for efficient MCP connections.")
    try:
        answer = input("install lazy-tool? [Y/n] ").strip().lower()
        if answer in ("n", "no"):
            return False
    except (EOFError, KeyboardInterrupt):
        return False

    return _install_lazy_tool()


# ── Config ──────────────────────────────────────────────────────────────────


def write_lazy_tool_config(mcp_servers: dict) -> None:
    """Write lazy-tool config pointing at the given MCP servers.

    mcp_servers format:
        {"notion": {"command": "npx", "args": [...], "env": {...}}, ...}
    """
    LAZY_TOOL_CONFIG.parent.mkdir(parents=True, exist_ok=True)

    config: dict = {
        "sources": [],
        "mode": "search",
        "cache": {"enabled": True, "ttl": 300},
    }

    for name, server in mcp_servers.items():
        config["sources"].append({
            "id": name,
            "name": name,
            "type": "server",
            "transport": "stdio",
            "command": server["command"],
            "args": server.get("args", []),
            "env": server.get("env", {}),
            "fallback": "passthrough",
        })

    LAZY_TOOL_CONFIG.write_text(yaml.dump(config, default_flow_style=False))


def build_mcp_servers_from_integrations() -> dict:
    """Read integrations.yaml and return the mcp_servers dict for write_lazy_tool_config.

    Only includes servers whose catalogue entry has routed_via_lazy_tool=True.
    Resolves env_vars to actual environment values.
    """
    from alfard.integrations.catalogue import CATALOGUE

    integrations_path = ALFARD_HOME / "config" / "integrations.yaml"
    if not integrations_path.exists():
        return {}

    load_env()

    with open(integrations_path) as f:
        data = yaml.safe_load(f) or {}

    result: dict = {}
    for entry in data.get("servers", []):
        name = entry.get("name", "")
        if not CATALOGUE.get(name, {}).get("routed_via_lazy_tool"):
            continue
        if entry.get("transport") not in ("stdio", "http"):
            continue

        env: dict = {}
        for key, env_var_name in entry.get("env_vars", {}).items():
            val = os.environ.get(env_var_name, "")
            if val:
                env[key] = val

        result[name] = {
            "command": entry["command"],
            "args": entry.get("args", []),
            "env": env,
        }

    return result


def reindex_lazy_tool() -> bool:
    """Rebuild lazy-tool's local SQLite catalog from current MCP servers."""
    if not LAZY_TOOL_CONFIG.exists():
        return False
    try:
        result = subprocess.run(
            ["lazy-tool", "reindex", "--config", str(LAZY_TOOL_CONFIG)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("  lazy-tool reindex timed out.")
        return False
    if result.returncode != 0:
        print(f"  lazy-tool reindex failed: {result.stderr.strip()}")
        return False
    return True


def update_lazy_tool_catalog() -> bool:
    """Rebuild config and reindex. Returns True on success."""
    servers = build_mcp_servers_from_integrations()
    if not servers:
        return False
    write_lazy_tool_config(servers)
    return reindex_lazy_tool()


# ── Server lifecycle ─────────────────────────────────────────────────────────


def start_lazy_tool_server() -> subprocess.Popen | None:
    """Start lazy-tool serve as a persistent background stdio process.

    Keeps the catalog warm so per-call spawns by MCPClient start faster.
    Returns the process handle; caller must register cleanup via atexit.
    Returns None if lazy-tool is unavailable or fails to start.
    """
    if not shutil.which("lazy-tool") or not LAZY_TOOL_CONFIG.exists():
        return None

    proc = subprocess.Popen(
        ["lazy-tool", "serve", "--config", str(LAZY_TOOL_CONFIG), "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(0.5)

    if proc.poll() is not None:
        return None

    return proc
