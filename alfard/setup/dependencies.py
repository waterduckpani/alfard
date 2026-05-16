"""Dependency installer — checks and installs required system dependencies for alfard."""

import subprocess
import shutil
import sys
import platform

from rich.console import Console

console = Console()


def check_node() -> bool:
    return shutil.which("node") is not None


def check_npm() -> bool:
    return shutil.which("npm") is not None


def check_brew() -> bool:
    return shutil.which("brew") is not None


def check_gws() -> bool:
    return shutil.which("gws") is not None


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


def install_gws() -> bool:
    """Install gws via npm. Returns True if successful."""
    console.print("[dim]Installing gws (Google Workspace CLI)...[/dim]")
    result = subprocess.run(
        ["npm", "install", "-g", "@googleworkspace/cli"],
        check=False
    )
    return result.returncode == 0


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

    # gws — only needed for Gmail/GDrive, not fatal if missing
    if check_gws():
        console.print("[dim]✓ gws found[/dim]")
    else:
        console.print("[dim]gws not found — installing...[/dim]")
        if install_gws():
            console.print("[dim]✓ gws installed[/dim]")
        else:
            console.print(
                "[dim]Could not install gws now. "
                "It will be installed when you connect Gmail.[/dim]"
            )

    return True
