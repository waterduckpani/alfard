"""Agent loader — reads agent markdown files and builds the system prompt injected into the orchestrator."""

from datetime import datetime
from pathlib import Path
from alfard.agents.base_prompt import BASE_PROMPT
from alfard.memory.manager import MemoryManager

AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"
SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

SOUL_FILE = "soul.md"
BRAIN_FILE = "brain.md"
MEMORY_FILE = "memory.md"


class AgentLoader:
    def __init__(self, agent_name: str) -> None:
        self.name = agent_name
        self.agent_dir = AGENTS_DIR / agent_name
        # Guard against path traversal (e.g. agent_name = "../config")
        try:
            self.agent_dir.resolve().relative_to(AGENTS_DIR.resolve())
        except ValueError:
            raise ValueError(
                f"Invalid agent name '{agent_name}': resolves outside agents directory."
            )
        if not self.agent_dir.exists():
            raise FileNotFoundError(f"Agent directory not found: {self.agent_dir}")
        self.memory_manager = MemoryManager(self.agent_dir)
        self.memory_manager.migrate_from_memory_md()

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

    def build_system_prompt(self, query: str = "") -> str:
        """Build the full system prompt for this agent.

        Injects soul, brain, relevant memories, and active skills.
        Memory is retrieved semantically based on the query.
        """
        parts = []

        # Base prompt
        from alfard.agents.base_prompt import BASE_PROMPT
        parts.append(BASE_PROMPT)

        # Soul
        soul = self._read_file("soul.md")
        if soul:
            parts.append(f"# Agent identity\n{soul}")

        # Brain (permanent facts — always injected)
        brain = self._read_file("brain.md")
        if brain:
            parts.append(f"# Permanent knowledge\n{brain}")

        # Memory context (semantic retrieval + recent sessions)
        memory_context = self.memory_manager.build_memory_context(query)
        if memory_context:
            parts.append(memory_context)

        # Skills (load all active skills)
        skills_dir = self.agent_dir / "skills"
        if skills_dir.exists():
            for skill_file in sorted(skills_dir.glob("*.md")):
                skill_content = skill_file.read_text(encoding="utf-8").strip()
                if skill_content:
                    skill_name = skill_file.stem
                    parts.append(
                        f"# {skill_name.capitalize()} skill\n{skill_content}"
                    )

        return "\n\n---\n\n".join(parts)

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
