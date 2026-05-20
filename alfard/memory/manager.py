"""Memory manager — unified interface for reading and writing
agent memory. Handles memories (vector store) and session
summaries (JSONL). Used by AgentLoader and Orchestrator."""

import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from alfard.memory.store import VectorStore

_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'-----BEGIN\s+(?:\w+\s+)?PRIVATE KEY-----'), "private key"),
    (re.compile(r'\bsk-[A-Za-z0-9_\-]{20,}'), "API key (sk- prefix)"),
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), "AWS access key ID"),
    (re.compile(r'\bgh[oprsu]_[A-Za-z0-9]{36}\b'), "GitHub token"),
    (re.compile(r'\bAIza[0-9A-Za-z\-_]{35}\b'), "Google API key"),
    (re.compile(r'\bxox[baprs]-[0-9]+-[0-9]+-[0-9]+-[a-f0-9]+\b'), "Slack token"),
    (re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}'), "bearer token"),
    (re.compile(r'(?i)(?:password|passwd|pwd)\s*[=:]\s*\S{8,}'), "password"),
]


def _check_secrets(content: str) -> str | None:
    """Return a description of the matched secret pattern, or None if clean."""
    for pattern, label in _SECRET_PATTERNS:
        if pattern.search(content):
            return label
    return None


class MemoryManager:
    """
    Manages two types of agent memory:

    1. Memories (brain.db) — permanent semantic memories stored
       as vectors. Retrieved by similarity to current context.

    2. Sessions (sessions.jsonl) — rolling window of last 5
       session summaries. Always injected into context.
    """

    MAX_SESSIONS = 5

    def __init__(self, agent_dir: Path):
        self.agent_dir = agent_dir
        self.brain_db = VectorStore(agent_dir / "brain.db")

        memory_dir = agent_dir / "memory"
        memory_dir.mkdir(exist_ok=True)
        self.sessions_path = memory_dir / "sessions.jsonl"

    # ── Memories ─────────────────────────────────────────────

    def write(
        self,
        content: str,
        *,
        memory_type: str = "fact",
        valence: str = "neutral",
        source: str = "agent_inferred",
        status: str = "active",
        confidence: float | None = None,
        importance: float | None = None,
        reason: str = "",
    ) -> str:
        """
        Store a permanent memory with conflict detection and secret blocking.

        Returns one of:
          "duplicate"         — near-identical memory of same valence exists (skipped)
          "conflict"          — near-identical memory of different valence exists
                                (new entry written with status=disputed)
          "blocked: <reason>" — content matched a secret pattern (never written)
          "remembered: ..."   — written successfully
        """
        secret = _check_secrets(content)
        if secret:
            return f"blocked: {secret}"

        write_status = status
        top = self.brain_db.search_typed(content, memory_type, top_k=1)
        if top:
            sim, _existing_content, existing_valence = top[0]
            if sim > 0.90:
                if existing_valence == valence:
                    return "duplicate"
                write_status = "disputed"

        default = 1.0 if source == "user_explicit" else 0.5
        resolved_confidence = confidence if confidence is not None else default
        resolved_importance = importance if importance is not None else default

        force = write_status == "disputed"
        self.brain_db.store(
            content,
            memory_type=memory_type,
            valence=valence,
            confidence=resolved_confidence,
            importance=resolved_importance,
            source=source,
            status=write_status,
            force=force,
        )

        self._export_brain_md()
        if memory_type == "project_state":
            self._export_project_state_md()

        if write_status == "disputed":
            return "conflict"
        return f"remembered: {content[:80]}"

    def store_fact(self, fact: str, tags: list[str] | None = None) -> str:
        """Backward-compatible wrapper — stores as user_explicit fact."""
        return self.write(fact, memory_type="fact", source="user_explicit")

    # ── Exports ──────────────────────────────────────────────

    def _export_brain_md(self) -> None:
        """Regenerate brain.md from all active memories, grouped by type."""
        all_memories = [m for m in self.brain_db.get_all() if m["status"] in ("active", "disputed")]
        all_memories.sort(key=lambda m: m["updated_at"], reverse=True)

        by_type: dict[str, list[dict]] = {}
        for m in all_memories:
            by_type.setdefault(m["type"], []).append(m)

        lines = [f"# brain — {self.agent_dir.name}", ""]
        for mem_type in sorted(by_type):
            lines.append(f"## {mem_type}")
            for m in by_type[mem_type]:
                suffix = ""
                if m["valence"] != "neutral":
                    suffix += f" *({m['valence']})*"
                if m["status"] == "disputed":
                    suffix += " *(disputed)*"
                lines.append(f"- {m['content']}{suffix}")
            lines.append("")

        brain_md = self.agent_dir / "brain.md"
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.agent_dir,
            delete=False,
            suffix=".tmp",
            encoding="utf-8",
        ) as tmp:
            tmp.write("\n".join(lines))
            tmp_path = tmp.name
        os.replace(tmp_path, brain_md)

    def _export_project_state_md(self) -> None:
        """Write the latest active project_state memory to memory/project_state.md."""
        candidates = [
            m for m in self.brain_db.get_all()
            if m["status"] == "active" and m["type"] == "project_state"
        ]
        if not candidates:
            return
        candidates.sort(key=lambda m: m["updated_at"], reverse=True)
        ps_path = self.agent_dir / "memory" / "project_state.md"
        ps_path.write_text(candidates[0]["content"], encoding="utf-8")

    def retrieve_relevant(self, query: str, top_k: int = 5) -> list[str]:
        """Return the most relevant memory contents for the given query."""
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

        sessions = self._load_sessions()
        sessions.append(entry)
        sessions = sessions[-self.MAX_SESSIONS:]

        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.sessions_path.parent,
            delete=False,
            suffix=".tmp",
            encoding="utf-8",
        ) as tmp:
            for s in sessions:
                tmp.write(json.dumps(s) + "\n")
            tmp_path = tmp.name

        os.replace(tmp_path, self.sessions_path)

    def get_recent_sessions(self, n: int = 3) -> list[dict]:
        """Return the n most recent session summaries."""
        return self._load_sessions()[-n:]

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

        recent = self.get_recent_sessions(n=3)
        if recent:
            session_lines = [f"[{s['date']}] {s['summary']}" for s in recent]
            sections.append(
                "[SOURCE: memory.sessions]\n"
                "## Recent sessions\n" + "\n".join(session_lines) +
                "\n[END SOURCE]"
            )

        if query and self.brain_db.count() > 0:
            facts = self.retrieve_relevant(query, top_k=5)
            if facts:
                fact_lines = [f"- {f}" for f in facts]
                sections.append(
                    "[SOURCE: memory.facts]\n"
                    "## Relevant memory\n" + "\n".join(fact_lines) +
                    "\n[END SOURCE]"
                )

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

        memory_md.rename(self.agent_dir / "memory.md.bak")
        return True
