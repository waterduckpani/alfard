"""Agent loader — reads agent markdown files and builds the system prompt injected into the orchestrator."""

from datetime import datetime
from pathlib import Path
from alfard.agents.base_prompt import BASE_PROMPT

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"
SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

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

    def get_agent_skills(self) -> list[str]:
        """Return list of skill names active for this agent."""
        skills_dir = self.agent_dir / "skills"
        if not skills_dir.exists():
            return []
        return sorted(
            p.stem for p in skills_dir.iterdir()
            if p.suffix == ".md"
        )

    def _load_agent_skills(self) -> str:
        """Load all skill files from this agent's skills folder."""
        skills_dir = self.agent_dir / "skills"
        if not skills_dir.exists():
            return ""
        parts = []
        for skill_file in sorted(skills_dir.glob("*.md")):
            parts.append(skill_file.read_text(encoding="utf-8"))
        return "\n\n".join(parts)

    def build_system_prompt(self) -> str:
        sections = [
            ("# Identity", self._read_file(SOUL_FILE)),
            ("# Knowledge", self._read_file(BRAIN_FILE)),
            ("# Recent Memory", self._read_file(MEMORY_FILE)),
        ]
        parts = [BASE_PROMPT.strip()]
        for header, content in sections:
            if content.strip():
                parts.append(f"{header}\n{content}")
        skills_content = self._load_agent_skills()
        if skills_content:
            parts.append(f"# Skills\n{skills_content}")
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


def add_skill(agent_name: str, skill_name: str) -> bool:
    """Copy a skill from the global library to an agent.
    Returns True if added, False if skill not found."""
    skill_source = SKILLS_DIR / f"{skill_name}.md"
    if not skill_source.exists():
        return False
    agent_skills_dir = AGENTS_DIR / agent_name / "skills"
    agent_skills_dir.mkdir(exist_ok=True)
    dest = agent_skills_dir / f"{skill_name}.md"
    dest.write_text(
        skill_source.read_text(encoding="utf-8"),
        encoding="utf-8"
    )
    return True


def remove_skill(agent_name: str, skill_name: str) -> bool:
    """Remove a skill from an agent.
    Returns True if removed, False if not found."""
    dest = AGENTS_DIR / agent_name / "skills" / f"{skill_name}.md"
    if not dest.exists():
        return False
    dest.unlink()
    return True


def list_available_skills() -> list[str]:
    """Return all skill names in the global skills library."""
    if not SKILLS_DIR.exists():
        return []
    return sorted(p.stem for p in SKILLS_DIR.glob("*.md"))
