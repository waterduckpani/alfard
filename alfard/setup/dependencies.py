"""Dependency installer — checks and installs required system dependencies for alfard."""

import json
import os
import stat
import subprocess
import shutil
import sys
import platform
import tempfile
from pathlib import Path

from rich.console import Console

console = Console()


def check_node() -> bool:
    return shutil.which("node") is not None


def check_npm() -> bool:
    return shutil.which("npm") is not None


def check_brew() -> bool:
    return shutil.which("brew") is not None


def check_gogcli() -> bool:
    return shutil.which("gog") is not None


def install_brew() -> bool:
    """Install Homebrew on macOS. Returns True if successful."""
    console.print("[dim]Installing Homebrew — this takes 2-3 minutes...[/dim]")
    result = subprocess.run(
        ["/bin/bash", "-c",
         "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"],
        check=False
    )
    return result.returncode == 0


def install_node() -> bool:
    """Install Node.js for the current platform. Returns True if successful."""
    system = platform.system()

    if system == "Darwin":
        if not check_brew():
            console.print("[dim]Homebrew not found — installing first...[/dim]")
            if not install_brew():
                console.print(
                    "[red]Could not install Homebrew.[/red]\n"
                    "Install manually: https://brew.sh then re-run alfard setup."
                )
                return False
        console.print("[dim]Installing Node.js via Homebrew...[/dim]")
        result = subprocess.run(["brew", "install", "node"], check=False)
        return result.returncode == 0

    elif system == "Linux":
        console.print("[dim]Installing Node.js...[/dim]")
        if shutil.which("apt"):
            result = subprocess.run(
                ["sudo", "apt", "install", "-y", "nodejs", "npm"], check=False
            )
            return result.returncode == 0
        elif shutil.which("snap"):
            result = subprocess.run(
                ["sudo", "snap", "install", "node", "--classic"], check=False
            )
            return result.returncode == 0
        else:
            console.print(
                "[red]Could not auto-install Node.js.[/red]\n"
                "Install manually: https://nodejs.org then re-run alfard setup."
            )
            return False

    elif system == "Windows":
        if shutil.which("winget"):
            console.print("[dim]Installing Node.js via winget...[/dim]")
            result = subprocess.run(
                ["winget", "install", "OpenJS.NodeJS", "--silent"], check=False
            )
            return result.returncode == 0
        else:
            console.print(
                "[red]Could not auto-install Node.js.[/red]\n"
                "Download from: https://nodejs.org then re-run alfard setup."
            )
            return False

    return False


def _install_gogcli_linux() -> bool:
    """Download the gogcli binary from GitHub releases and install to ~/.local/bin/gog."""
    arch = platform.machine()
    arch_map = {"x86_64": "amd64", "aarch64": "arm64"}
    gog_arch = arch_map.get(arch)
    if not gog_arch:
        console.print(f"[red]Unsupported architecture: {arch}[/red]")
        return False

    import urllib.request
    try:
        with urllib.request.urlopen(
            "https://api.github.com/repos/openclaw/gogcli/releases/latest",
            timeout=10,
        ) as r:
            version = json.loads(r.read())["tag_name"].lstrip("v")
    except Exception:
        console.print("[red]Could not fetch latest gogcli version. Check your connection.[/red]")
        return False

    url = (
        f"https://github.com/openclaw/gogcli/releases/download/v{version}/"
        f"gogcli_{version}_linux_{gog_arch}.tar.gz"
    )
    install_dir = Path.home() / ".local" / "bin"
    install_dir.mkdir(parents=True, exist_ok=True)
    dest = install_dir / "gog"

    console.print(f"[dim]Downloading gogcli v{version}...[/dim]")
    try:
        import tarfile
        tmp_tar = Path(tempfile.gettempdir()) / f"gogcli_{version}.tar.gz"
        urllib.request.urlretrieve(url, tmp_tar)
        with tarfile.open(tmp_tar) as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith("gog"))
            member.name = "gog"
            tar.extract(member, path=install_dir)
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
        tmp_tar.unlink()
    except Exception as exc:
        console.print(f"[red]Install failed: {exc}[/red]")
        return False

    os.environ["PATH"] = f"{install_dir}:{os.environ.get('PATH', '')}"
    console.print(f"[dim]gogcli installed to {dest}[/dim]")
    console.print(
        "[dim]Add to your shell permanently:\n"
        "  echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.bashrc[/dim]"
    )
    return True


def _install_gogcli_windows() -> bool:
    """Download the gogcli Windows binary from GitHub releases and install to ~/.local/bin/gog.exe."""
    import urllib.request
    try:
        with urllib.request.urlopen(
            "https://api.github.com/repos/openclaw/gogcli/releases/latest",
            timeout=10,
        ) as r:
            version = json.loads(r.read())["tag_name"].lstrip("v")
    except Exception:
        console.print("[red]Could not fetch latest gogcli version. Check your connection.[/red]")
        return False

    url = (
        f"https://github.com/openclaw/gogcli/releases/download/v{version}/"
        f"gogcli_{version}_windows_amd64.zip"
    )
    install_dir = Path.home() / ".local" / "bin"
    install_dir.mkdir(parents=True, exist_ok=True)
    dest = install_dir / "gog.exe"

    console.print(f"[dim]Downloading gogcli v{version}...[/dim]")
    try:
        import zipfile
        tmp_zip = Path(tempfile.gettempdir()) / f"gogcli_{version}.zip"
        urllib.request.urlretrieve(url, tmp_zip)
        with zipfile.ZipFile(tmp_zip) as zf:
            member = next(n for n in zf.namelist() if n.endswith(".exe"))
            dest.write_bytes(zf.read(member))
        tmp_zip.unlink()
    except Exception as exc:
        console.print(f"[red]Install failed: {exc}[/red]")
        return False

    os.environ["PATH"] = f"{install_dir};{os.environ.get('PATH', '')}"
    console.print(f"[dim]gogcli installed to {dest}[/dim]")
    return True


def install_gogcli() -> bool:
    """Install gogcli for the current platform. Returns True if successful."""
    console.print("[dim]Installing gogcli (Google Workspace CLI)...[/dim]")
    if sys.platform == "darwin":
        if not check_brew():
            console.print(
                "[red]Homebrew not found.[/red]\n"
                "Install from https://brew.sh then re-run alfard setup."
            )
            return False
        result = subprocess.run(["brew", "install", "gogcli"], check=False)
        return result.returncode == 0
    if sys.platform == "linux":
        return _install_gogcli_linux()
    if sys.platform == "win32":
        return _install_gogcli_windows()
    return False


def ensure_dependencies() -> bool:
    """
    Check and install all required dependencies.
    Returns True if all critical dependencies are available.
    Called at the start of alfard setup.
    """
    # Node.js
    if check_node():
        console.print("[dim]✓ Node.js found[/dim]")
    else:
        console.print("[dim]Node.js not found — installing...[/dim]")
        if install_node():
            console.print("[dim]✓ Node.js installed[/dim]")
        else:
            return False

    # gogcli — only needed for Gmail/GDrive, not fatal if missing
    if check_gogcli():
        console.print("[dim]✓ gogcli found[/dim]")
    else:
        console.print("[dim]gogcli not found — installing...[/dim]")
        if install_gogcli():
            console.print("[dim]✓ gogcli installed[/dim]")
        else:
            console.print(
                "[dim]Could not install gogcli now. "
                "It will be installed when you connect Gmail.[/dim]"
            )

    return True
