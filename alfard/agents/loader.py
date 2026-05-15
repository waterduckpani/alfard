"""Agent loader — reads agent markdown files and builds the system prompt injected into the orchestrator."""

from datetime import datetime
from pathlib import Path

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"

SOUL_FILE = "soul.md"
BRAIN_FILE = "brain.md"
MEMORY_FILE = "memory.md"


class AgentLoader:
    def __init__(self, agent_name: str) -> None:
        self.name = agent_name
        self.agent_dir = AGENTS_DIR / agent_name
        if not self.agent_dir.exists():
            raise FileNotFoundError(f"Agent directory not found: {self.agent_dir}")

    def _read_file(self, filename: str) -> str:
        path = self.agent_dir / filename
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def build_system_prompt(self) -> str:
        sections = [
            ("# Identity", self._read_file(SOUL_FILE)),
            ("# Knowledge", self._read_file(BRAIN_FILE)),
            ("# Recent Memory", self._read_file(MEMORY_FILE)),
        ]
        parts = []
        for header, content in sections:
            if content:
                parts.append(f"{header}\n{content}")
        return "\n\n".join(parts)

    def save_memory(self, content: str) -> None:
        path = self.agent_dir / MEMORY_FILE
        path.write_text(content, encoding="utf-8")

    def append_brain(self, content: str) -> None:
        path = self.agent_dir / BRAIN_FILE
        entry = f"\n[{datetime.utcnow().isoformat()}Z]\n{content}\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)


def list_agents() -> list[str]:
    if not AGENTS_DIR.exists():
        return []
    return sorted(p.name for p in AGENTS_DIR.iterdir() if p.is_dir())
