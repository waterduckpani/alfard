"""Memory manager — unified interface for reading and writing
agent memory. Handles memories (vector store) and session
summaries (JSONL). Used by AgentLoader and Orchestrator."""

import json
import math
import os
import re
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from alfard.memory.embedder import cosine_similarity, get_embedding
from alfard.memory.store import VectorStore

if TYPE_CHECKING:
    from alfard.llm.client import LLMClient

_VALID_VALENCES: frozenset[str] = frozenset({"positive", "negative", "neutral"})
_VALID_REFLECT_TYPES: frozenset[str] = frozenset({
    "fact", "procedure", "mistake", "tool_pattern", "goal",
    "decision", "person", "preference", "constraint", "project_state",
})

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

    2. Sessions (sessions.db) — episodic store of up to 20 past
       session summaries with embeddings for similarity retrieval.
    """

    MAX_SESSIONS = 20

    _TYPE_CAPS: dict[str, int] = {
        "fact": 100,
        "procedure": 50,
        "mistake": 50,
        "tool_pattern": 50,
        "goal": 30,
        "decision": 30,
        "person": 30,
        "preference": 30,
        "constraint": 20,
        "project_state": 10,
    }
    _OVERALL_CAP = 500

    def __init__(self, agent_dir: Path):
        self.agent_dir = agent_dir
        self.brain_db = VectorStore(agent_dir / "brain.db")

        memory_dir = agent_dir / "memory"
        memory_dir.mkdir(exist_ok=True)
        self.sessions_db = memory_dir / "sessions.db"
        self._init_sessions_db()

    # ── Sessions DB ──────────────────────────────────────────

    def _connect_sessions(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sessions_db)
        conn.row_factory = sqlite3.Row
        return conn

    def get_session_count(self) -> int:
        """Return the total number of saved sessions."""
        with self._connect_sessions() as conn:
            return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    def _session_threshold(self, n: int) -> float | None:
        """Return the created_at of the session n positions back, or None if fewer than n sessions exist."""
        with self._connect_sessions() as conn:
            rows = conn.execute(
                "SELECT created_at FROM sessions ORDER BY created_at DESC LIMIT ?",
                (n + 1,),
            ).fetchall()
        if len(rows) <= n:
            return None
        return rows[n]["created_at"]

    def _init_sessions_db(self) -> None:
        with self._connect_sessions() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id         TEXT PRIMARY KEY,
                    summary    TEXT NOT NULL,
                    topics     TEXT NOT NULL,
                    turn_count INTEGER NOT NULL,
                    outcome    TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    embedding  TEXT NOT NULL
                )
            """)
            conn.commit()
        os.chmod(self.sessions_db, 0o600)

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
            if sim > 0.80:
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

    def retrieve(self, query: str, top_k: int = 8) -> list[dict]:
        """Score every active memory and return top_k by composite score.

        score = (0.40 × relevance) + (0.35 × recency) + (0.25 × importance × confidence)
        relevance = cosine similarity to query embedding
        recency   = exp(−0.995 × hours_since_last_accessed); None → 0 hours (score=1.0)
        negative valence  → multiply final score by 1.5
        type=project_state → score fixed at 1.0 (always surfaces first)

        Returns dicts with all memory fields plus a "score" key, sorted descending.
        """
        if self.brain_db.count() == 0:
            return []

        try:
            query_embedding = get_embedding(query)
        except RuntimeError:
            query_embedding = None
        rows = self.brain_db.get_active_full()
        now = time.time()

        scored: list[dict] = []
        for row in rows:
            if row["type"] == "project_state":
                score = 1.0
            else:
                relevance = (
                    cosine_similarity(query_embedding, json.loads(row["embedding"]))
                    if query_embedding is not None
                    else 0.0
                )
                hours = (
                    (now - row["last_accessed_at"]) / 3600.0
                    if row["last_accessed_at"] is not None
                    else 0.0
                )
                recency = math.exp(-0.995 * hours)
                score = (
                    0.40 * relevance
                    + 0.35 * recency
                    + 0.25 * row["importance"] * row["confidence"]
                )
                if row["valence"] == "negative":
                    score *= 1.5

            scored.append({**row, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[:top_k]
        self.brain_db.touch_many([r["id"] for r in top])
        return top

    def get_fact_count(self) -> int:
        return self.brain_db.count()

    def complete_goal(self, query: str) -> str | None:
        """Mark the closest active goal complete if similarity > 0.75.

        Returns the goal content, or None if no match.
        """
        try:
            query_embedding = get_embedding(query)
        except RuntimeError:
            return None
        with self.brain_db._connect() as conn:
            rows = conn.execute(
                """SELECT m.id, m.content, e.embedding
                   FROM memories m
                   JOIN embeddings e ON e.memory_id = m.id
                   WHERE m.status = 'active' AND m.type = 'goal'"""
            ).fetchall()
        if not rows:
            return None

        best_sim, best_id, best_content = -1.0, None, None
        for row in rows:
            sim = cosine_similarity(query_embedding, json.loads(row["embedding"]))
            if sim > best_sim:
                best_sim, best_id, best_content = sim, row["id"], row["content"]

        if best_sim <= 0.75:
            return None

        now = time.time()
        with self.brain_db._connect() as conn:
            conn.execute(
                "UPDATE memories SET status = 'complete', updated_at = ? WHERE id = ?",
                (now, best_id),
            )
            conn.commit()
        self._export_brain_md()
        return best_content

    def mark_stale_goals(self, current_session_count: int) -> int:
        """Mark active goals stale when last_accessed_at is older than 15 sessions.

        Returns number of goals marked stale.
        """
        if current_session_count <= 15:
            return 0
        threshold = self._session_threshold(15)
        if threshold is None:
            return 0

        now = time.time()
        with self.brain_db._connect() as conn:
            result = conn.execute(
                """UPDATE memories SET status = 'stale', updated_at = ?
                   WHERE type = 'goal' AND status = 'active'
                     AND last_accessed_at IS NOT NULL AND last_accessed_at < ?""",
                (now, threshold),
            )
            count = result.rowcount
            conn.commit()
        if count:
            self._export_brain_md()
        return count

    def enforce_caps(self) -> int:
        """Archive lowest-scoring memories that exceed per-type or overall caps.

        Scores without a query: recency + intrinsic quality only (relevance term omitted).
        Returns number of memories archived.
        """
        rows = self.brain_db.get_active_full()
        if not rows:
            return 0

        now = time.time()

        def _score(row: dict) -> float:
            if row["type"] == "project_state":
                return 1.0
            hours = (
                (now - row["last_accessed_at"]) / 3600.0
                if row["last_accessed_at"] is not None
                else 0.0
            )
            recency = math.exp(-0.995 * hours)
            score = 0.35 * recency + 0.25 * row["importance"] * row["confidence"]
            if row["valence"] == "negative":
                score *= 1.5
            return score

        scored = sorted(
            [{"id": r["id"], "type": r["type"], "score": _score(r)} for r in rows],
            key=lambda x: x["score"],
        )

        to_archive: set[str] = set()

        by_type: dict[str, list[dict]] = {}
        for item in scored:
            by_type.setdefault(item["type"], []).append(item)

        for mem_type, cap in self._TYPE_CAPS.items():
            group = by_type.get(mem_type, [])
            excess = len(group) - cap
            if excess > 0:
                for item in group[:excess]:
                    to_archive.add(item["id"])

        remaining = [item for item in scored if item["id"] not in to_archive]
        overall_excess = len(remaining) - self._OVERALL_CAP
        if overall_excess > 0:
            for item in remaining[:overall_excess]:
                to_archive.add(item["id"])

        if not to_archive:
            return 0

        with self.brain_db._connect() as conn:
            conn.executemany(
                "UPDATE memories SET status = 'archived', updated_at = ? WHERE id = ?",
                [(now, mid) for mid in to_archive],
            )
            conn.commit()
        self._export_brain_md()
        return len(to_archive)

    def archive_old_memories(self) -> int:
        """Archive complete, stale, and low-confidence unused memories.

        Returns number of memories archived.
        """
        now = time.time()
        ninety_days_ago = now - 90 * 24 * 3600
        threshold_20 = self._session_threshold(20)

        total = 0
        with self.brain_db._connect() as conn:
            r = conn.execute(
                """UPDATE memories SET status = 'archived', updated_at = ?
                   WHERE status = 'complete' AND updated_at < ?""",
                (now, ninety_days_ago),
            )
            total += r.rowcount
            r = conn.execute(
                "UPDATE memories SET status = 'archived', updated_at = ? WHERE status = 'stale'",
                (now,),
            )
            total += r.rowcount
            if threshold_20 is not None:
                r = conn.execute(
                    """UPDATE memories SET status = 'archived', updated_at = ?
                       WHERE status = 'active' AND confidence < 0.4
                         AND usage_count = 0
                         AND last_accessed_at IS NOT NULL AND last_accessed_at < ?""",
                    (now, threshold_20),
                )
                total += r.rowcount
            conn.commit()
        if total:
            self._export_brain_md()
        return total

    # ── Sessions ─────────────────────────────────────────────

    def save_session(self, summary: str, topics: list[str],
                     turn_count: int, outcome: str) -> None:
        """
        Embed the summary and write a row to sessions.db.
        Trims to the MAX_SESSIONS most recent rows after inserting.
        """
        try:
            embedding = get_embedding(summary)
        except RuntimeError:
            embedding = None
        now = time.time()
        session_id = str(uuid.uuid4())
        with self._connect_sessions() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (id, summary, topics, turn_count, outcome, created_at, embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, summary, json.dumps(topics),
                 turn_count, outcome, now, json.dumps(embedding)),
            )
            conn.execute(
                """DELETE FROM sessions WHERE id NOT IN (
                   SELECT id FROM sessions ORDER BY created_at DESC LIMIT ?
                )""",
                (self.MAX_SESSIONS,),
            )
            conn.commit()

    def retrieve_sessions(self, query: str, top_k: int = 2) -> list[dict]:
        """
        Return sessions to inject into context.
        Slot 0 is always the most recent session.
        Then up to top_k more are chosen by cosine similarity to query.
        Deduplicates so the same session never appears twice.
        """
        with self._connect_sessions() as conn:
            rows = conn.execute(
                """SELECT id, summary, topics, turn_count, outcome, created_at, embedding
                   FROM sessions ORDER BY created_at DESC"""
            ).fetchall()

        if not rows:
            return []

        sessions = []
        for r in rows:
            d = dict(r)
            d["date"] = datetime.utcfromtimestamp(d["created_at"]).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            d["topics"] = json.loads(d["topics"])
            sessions.append(d)

        result = [sessions[0]]
        seen = {sessions[0]["id"]}

        if len(sessions) > 1 and top_k > 0 and query:
            try:
                query_embedding = get_embedding(query)
                candidates = [
                    s for s in sessions[1:]
                    if json.loads(s["embedding"]) is not None
                ]
                scored = [
                    (cosine_similarity(query_embedding, json.loads(s["embedding"])), s)
                    for s in candidates
                ]
                scored.sort(reverse=True, key=lambda x: x[0])
                for _, s in scored[:top_k]:
                    if s["id"] not in seen:
                        result.append(s)
                        seen.add(s["id"])
            except RuntimeError:
                pass  # no embeddings available; fall back to recency only

        return result

    def get_recent_sessions(self, n: int = 3) -> list[dict]:
        """Return the n most recent session summaries, oldest first."""
        with self._connect_sessions() as conn:
            rows = conn.execute(
                """SELECT id, summary, topics, turn_count, outcome, created_at
                   FROM sessions ORDER BY created_at DESC LIMIT ?""",
                (n,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["date"] = datetime.utcfromtimestamp(d["created_at"]).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            d["topics"] = json.loads(d["topics"])
            result.append(d)
        result.reverse()
        return result

    def run_reflect(self, llm_client: "LLMClient", audit_log_path: Path) -> int:
        """Analyze the last 10 sessions and propose memory improvements.

        Triggered only when session count is a non-zero multiple of 10.
        Proposals are appended to memory/proposals.jsonl.
        Returns the number of new proposals written.
        """
        count = self.get_session_count()
        if count == 0 or count % 10 != 0:
            return 0

        sessions = self.get_recent_sessions(10)
        summaries = "\n".join(
            f"[{s['date']}] {s['summary']} (outcome: {s['outcome']}, turns: {s['turn_count']})"
            for s in sessions
        )

        all_memories = self.brain_db.get_all()
        mistakes = [m for m in all_memories if m["type"] == "mistake" and m["status"] == "active"]
        mistake_text = "\n".join(f"- {m['content']}" for m in mistakes) or "none"

        failure_lines: list[str] = []
        if audit_log_path.exists():
            session_end_events: list[dict] = []
            with open(audit_log_path, encoding="utf-8") as fh:
                for raw_line in fh:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        ev = json.loads(raw_line)
                        if ev.get("type") == "session_end":
                            session_end_events.append(ev)
                    except json.JSONDecodeError:
                        continue
            for ev in session_end_events[-10:]:
                failure_lines.append(
                    f"outcome={ev.get('outcome')} failed={ev.get('tool_calls_failed')} "
                    f"corrections={ev.get('corrections_detected')} turns={ev.get('turns')}"
                )
        failure_text = "\n".join(failure_lines) or "none"

        prompt = (
            "You are analyzing an AI agent's recent performance.\n"
            f"Here are the last 10 session summaries:\n{summaries}\n\n"
            f"Active mistakes on record:\n{mistake_text}\n\n"
            f"Failure signals:\n{failure_text}\n\n"
            "Propose up to 5 memory improvements. For each, output:\n"
            "TYPE: <memory type>\n"
            "VALENCE: <positive|negative|neutral>\n"
            "CONTENT: <the memory entry, one line>\n"
            "REASON: <why this should be remembered, one line>\n"
            "---"
        )

        response = llm_client.complete([{"role": "user", "content": prompt}])
        raw = (response.get("content") or "").strip()
        if not raw:
            return 0

        proposals: list[dict] = []
        now = datetime.utcnow().isoformat() + "Z"
        for block in raw.split("---"):
            block = block.strip()
            if not block:
                continue
            entry: dict = {"proposed_at": now, "status": "pending"}
            for line in block.splitlines():
                upper = line.upper()
                if upper.startswith("TYPE:"):
                    entry["type"] = line[5:].strip()
                elif upper.startswith("VALENCE:"):
                    entry["valence"] = line[8:].strip()
                elif upper.startswith("CONTENT:"):
                    entry["content"] = line[8:].strip()
                elif upper.startswith("REASON:"):
                    entry["reason"] = line[7:].strip()
            if "content" not in entry or "type" not in entry:
                continue
            if entry["type"] not in _VALID_REFLECT_TYPES:
                continue
            if entry.get("valence") and entry["valence"] not in _VALID_VALENCES:
                continue
            proposals.append(entry)

        if not proposals:
            return 0

        proposals_path = self.agent_dir / "memory" / "proposals.jsonl"
        rejected_contents: set[str] = set()
        if proposals_path.exists():
            for line in proposals_path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                    if entry.get("status") == "rejected":
                        rejected_contents.add(entry["content"].strip().lower())
                except (json.JSONDecodeError, KeyError):
                    pass

        new_proposals = [
            p for p in proposals
            if p["content"].strip().lower() not in rejected_contents
        ]
        if not new_proposals:
            return 0

        with open(proposals_path, "a", encoding="utf-8") as fh:
            for proposal in new_proposals:
                fh.write(json.dumps(proposal) + "\n")

        return len(new_proposals)

    # ── Context building ─────────────────────────────────────

    def build_memory_context(self, query: str) -> str:
        """
        Build the memory section of the system prompt.
        Called at session start with the agent's first message.
        Returns a formatted string ready for injection.
        """
        sections = []

        recent = self.retrieve_sessions(query)
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
                turn_count=0,
                outcome="migrated",
            )

        memory_md.rename(self.agent_dir / "memory.md.bak")
        return True
