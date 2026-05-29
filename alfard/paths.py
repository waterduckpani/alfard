"""Central path constants for the alfard package."""

import os
import sys
from pathlib import Path

ALFARD_HOME = Path.home() / ".alfard"
ENV_PATH = ALFARD_HOME / ".env"
USER_SKILLS_DIR = ALFARD_HOME / "skills"


def load_env() -> None:
    """Load credentials from ~/.alfard into the process environment."""
    from alfard.security.keystore import encrypt_env, decrypt_env, KeystoreError

    plain_path = ALFARD_HOME / ".env"
    enc_path = ALFARD_HOME / ".env.enc"

    if plain_path.exists():
        try:
            encrypt_env(ALFARD_HOME)
        except Exception:
            from rich.console import Console
            _c = Console()
            _c.print("[yellow]⚠ Could not encrypt .env — continuing with plaintext.[/yellow]")
            _c.print(
                "[yellow]  Run 'pip install cryptography' to enable encryption. "
                "Credentials are unprotected until then.[/yellow]"
            )
            from dotenv import load_dotenv
            load_dotenv(plain_path)
            return

    if enc_path.exists():
        try:
            env_vars = decrypt_env(ALFARD_HOME)
            for k, v in env_vars.items():
                os.environ.setdefault(k, v)
        except KeystoreError as exc:
            from rich.console import Console
            Console().print(f"[red]Error: {exc}[/red]")
            sys.exit(1)
