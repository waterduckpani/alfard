"""Agent loader — reads agent markdown files and builds the system prompt injected into the orchestrator."""

from datetime import datetime
from pathlib import Path
from alfard.agents.base_prompt import BASE_PROMPT
from alfard.memory.manager import MemoryManager
from alfard.paths import ALFARD_HOME, USER_SKILLS_DIR

AGENTS_DIR = ALFARD_HOME / "agents"
SKILLS_DIR = Path(__file__).parent.parent / "skills"

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

    def build_system_prompt(self, query: str = "", linked_skills: list[str] | None = None) -> str:
        """Build the full system prompt for this agent.

        Always injects: soul, project_state, last session.
        Then retrieves top 8 memories scored by relevance/recency/importance
        and groups them into What I know / How I work / Watch out sections.
        Query should be the user's first message so retrieval is task-relevant.
        """
        parts = []

        parts.append(BASE_PROMPT)

        # Always: soul
        soul = self._read_file("soul.md")
        if soul:
            parts.append(f"# Agent identity\n{soul}")

        # Always: project state
        project_state = self._read_file("memory/project_state.md")
        if project_state:
            parts.append(f"# Project state\n{project_state}")

        # Fixed memory orientation — always present
        parts.append(
            "## Memory\n"
            "You have a persistent memory system (brain.db). Use the memory write "
            "tool to store information. Rules are in your memory skill. "
            "The ╭─ remembered ╮ notification is system-generated — "
            "never produce it yourself."
        )

        # Always: most recent session + query-relevant past sessions
        sessions = self.memory_manager.retrieve_sessions(query)
        if sessions:
            label = "# Last session" if len(sessions) == 1 else "# Recent sessions"
            lines = [f"[{s['date']}] {s['summary']}" for s in sessions]
            parts.append(f"{label}\n" + "\n".join(lines))

        # Structured retrieval
        memories = self.memory_manager.retrieve(query, top_k=8)
        # project_state already injected above; exclude from grouped sections
        memories = [m for m in memories if m["type"] != "project_state"]

        _KNOW = {"fact", "decision", "person", "constraint"}
        _WORK = {"procedure", "tool_pattern", "preference"}

        know  = [m for m in memories if m["type"] in _KNOW and m["valence"] != "negative"]
        work  = [m for m in memories if m["type"] in _WORK and m["valence"] != "negative"]
        watch = [m for m in memories if m["valence"] == "negative"]

        mem_sections: list[str] = []
        if know:
            mem_sections.append("## What I know\n" + "\n".join(f"- {m['content']}" for m in know))
        if work:
            mem_sections.append("## How I work\n" + "\n".join(f"- {m['content']}" for m in work))
        if watch:
            mem_sections.append("## Watch out\n" + "\n".join(f"- {m['content']}" for m in watch))

        if mem_sections:
            parts.append("# Memory\n" + "\n\n".join(mem_sections))

        # memory.md is always injected — it defines how the memory system works
        if SKILLS_DIR.exists():
            _memory = SKILLS_DIR / "memory.md"
            if _memory.exists():
                parts.append(f"# Memory skill\n{_memory.read_text(encoding='utf-8').strip()}")

        # Agent-specific skills (explicitly added via add_skill)
        # linked_skills: if set, only load those named skills (cron filter); None = load all.
        skills_dir = self.agent_dir / "skills"
        if skills_dir.exists():
            for skill_file in sorted(skills_dir.glob("*.md")):
                if skill_file.name == "memory.md":
                    continue  # already loaded above
                if linked_skills is not None and skill_file.stem not in linked_skills:
                    continue
                skill_content = skill_file.read_text(encoding="utf-8").strip()
                if skill_content:
                    parts.append(f"# {skill_file.stem.capitalize()} skill\n{skill_content}")

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
    user_source = USER_SKILLS_DIR / f"{skill_name}.md"
    pkg_source = SKILLS_DIR / f"{skill_name}.md"
    skill_source = user_source if user_source.exists() else pkg_source
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
    """Return all skill names from the package library and USER_SKILLS_DIR combined."""
    USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    pkg = [p.stem for p in SKILLS_DIR.glob("*.md")] if SKILLS_DIR.exists() else []
    user = [p.stem for p in USER_SKILLS_DIR.glob("*.md")]
    pkg_set = set(pkg)
    return sorted(pkg) + sorted(s for s in user if s not in pkg_set)
