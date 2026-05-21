"""Central path constants for the alfard package."""

from pathlib import Path

ALFARD_HOME = Path.home() / ".alfard"
ENV_PATH = ALFARD_HOME / ".env"
USER_SKILLS_DIR = ALFARD_HOME / "skills"


def load_env() -> None:
    """Load ALFARD_HOME/.env into the process environment."""
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
