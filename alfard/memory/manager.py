"""Memory manager — unified interface for reading and writing
agent memory. Handles facts (vector store) and session
summaries (JSONL). Used by AgentLoader and Orchestrator."""

import json
import time
from datetime import datetime
from pathlib import Path
from alfard.memory.store import VectorStore


class MemoryManager:
    """
    Manages two types of agent memory:

    1. Facts (brain.db) — permanent semantic memories stored
       as vectors. Retrieved by similarity to current context.

    2. Sessions (sessions.jsonl) — rolling window of last 5
       session summaries. Always injected into context.
    """

    MAX_SESSIONS = 5

    def __init__(self, agent_dir: Path):
        self.agent_dir = agent_dir
        self.brain_db = VectorStore(agent_dir / "brain.db")

        # Session storage
        memory_dir = agent_dir / "memory"
        memory_dir.mkdir(exist_ok=True)
        self.sessions_path = memory_dir / "sessions.jsonl"

    # ── Facts ────────────────────────────────────────────────

    def store_fact(self, fact: str, tags: list[str] | None = None) -> str:
        """
        Store a permanent fact about the user or their work.
        Skips if a very similar fact already exists.
        Returns confirmation string.
        """
        fact_id = self.brain_db.store(fact, tags or [])
        return f"Remembered: {fact}"

    def retrieve_relevant(self, query: str, top_k: int = 5) -> list[str]:
        """
        Retrieve the most relevant facts for the given query.
        Returns list of fact strings.
        """
        try:
            return self.brain_db.search(query, top_k=top_k)
        except Exception:
            return []

    def get_fact_count(self) -> int:
        return self.brain_db.count()

    # ── Sessions ─────────────────────────────────────────────

    def save_session(self, summary: str, topics: list[str],
                     turns: int, facts_learned: int = 0) -> None:
        """
        Append a session summary to sessions.jsonl.
        Keeps only the last MAX_SESSIONS entries.
        """
        entry = {
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "turns": turns,
            "topics": topics,
            "summary": summary,
            "facts_learned": facts_learned,
        }

        # Load existing sessions
        sessions = self._load_sessions()
        sessions.append(entry)

        # Keep only last MAX_SESSIONS
        sessions = sessions[-self.MAX_SESSIONS:]

        # Write back
        with open(self.sessions_path, "w", encoding="utf-8") as f:
            for s in sessions:
                f.write(json.dumps(s) + "\n")

    def get_recent_sessions(self, n: int = 3) -> list[dict]:
        """Return the n most recent session summaries."""
        sessions = self._load_sessions()
        return sessions[-n:]

    def _load_sessions(self) -> list[dict]:
        if not self.sessions_path.exists():
            return []
        sessions = []
        with open(self.sessions_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        sessions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return sessions

    # ── Context building ─────────────────────────────────────

    def build_memory_context(self, query: str) -> str:
        """
        Build the memory section of the system prompt.
        Called at session start with the agent's first message.
        Returns a formatted string ready for injection.
        """
        sections = []

        # Recent sessions
        recent = self.get_recent_sessions(n=3)
        if recent:
            session_lines = []
            for s in recent:
                session_lines.append(
                    f"[{s['date']}] {s['summary']}"
                )
            sections.append(
                "## Recent sessions\n" + "\n".join(session_lines)
            )

        # Relevant facts from vector store
        if query and self.brain_db.count() > 0:
            facts = self.retrieve_relevant(query, top_k=5)
            if facts:
                fact_lines = [f"- {f}" for f in facts]
                sections.append(
                    "## Relevant memory\n" + "\n".join(fact_lines)
                )

        if not sections:
            return ""

        return "\n\n".join(sections)

    # ── Migration ────────────────────────────────────────────

    def migrate_from_memory_md(self) -> bool:
        """
        One-time migration: if memory.md exists, read it and
        store its content as a session summary, then rename it.
        Returns True if migration was performed.
        """
        memory_md = self.agent_dir / "memory.md"
        if not memory_md.exists():
            return False

        content = memory_md.read_text(encoding="utf-8").strip()
        if content:
            self.save_session(
                summary=content[:500],
                topics=["migrated from memory.md"],
                turns=0,
                facts_learned=0,
            )

        # Rename so migration doesn't run again
        memory_md.rename(self.agent_dir / "memory.md.bak")
        return True
