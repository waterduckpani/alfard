"""SQLite vector store — stores typed memories with embeddings for
semantic retrieval. Embeddings live in a separate linked table."""

import os
import sqlite3
import json
import time
import uuid
from pathlib import Path
from alfard.memory.embedder import get_embedding, cosine_similarity


class VectorStore:
    """
    Lightweight SQLite-based vector store for agent memories.
    Memories and embeddings are stored in separate linked tables.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_legacy()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id               TEXT PRIMARY KEY,
                    type             TEXT NOT NULL DEFAULT 'fact',
                    valence          TEXT NOT NULL DEFAULT 'neutral',
                    content          TEXT NOT NULL,
                    confidence       REAL NOT NULL DEFAULT 0.5,
                    importance       REAL NOT NULL DEFAULT 0.5,
                    source           TEXT NOT NULL DEFAULT 'agent_inferred',
                    usage_count      INTEGER NOT NULL DEFAULT 0,
                    status           TEXT NOT NULL DEFAULT 'active',
                    created_at       REAL NOT NULL,
                    updated_at       REAL NOT NULL,
                    last_accessed_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embeddings (
                    id        TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    embedding TEXT NOT NULL
                )
            """)
            conn.commit()
        os.chmod(self.db_path, 0o600)

    def _migrate_legacy(self) -> None:
        """
        One-time migration: import any rows from the old 'facts' table into
        'memories' as type=fact, valence=neutral, confidence=0.5,
        source=agent_inferred. Drops 'facts' table when done.
        """
        with self._connect() as conn:
            has_facts = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
            ).fetchone()
            if not has_facts:
                return

            rows = conn.execute(
                "SELECT fact, embedding, created_at, access_count FROM facts"
            ).fetchall()

            if not rows:
                conn.execute("DROP TABLE facts")
                conn.commit()
                return

            now = time.time()
            migrated = 0
            for row in rows:
                mem_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO memories
                       (id, type, valence, content, confidence, importance,
                        source, usage_count, status,
                        created_at, updated_at, last_accessed_at)
                       VALUES (?, 'fact', 'neutral', ?, 0.5, 0.5,
                               'agent_inferred', ?, 'active', ?, ?, NULL)""",
                    (mem_id, row["fact"], row["access_count"],
                     row["created_at"], now),
                )
                conn.execute(
                    "INSERT INTO embeddings (id, memory_id, embedding) VALUES (?, ?, ?)",
                    (str(uuid.uuid4()), mem_id, row["embedding"]),
                )
                migrated += 1

            conn.execute("DROP TABLE facts")
            conn.commit()

        if migrated:
            print(f"[memory] migrated {migrated} legacy fact(s) to new schema")

    def store(
        self,
        content: str,
        *,
        memory_type: str = "fact",
        valence: str = "neutral",
        confidence: float = 0.5,
        importance: float = 0.5,
        source: str = "agent_inferred",
        status: str = "active",
        force: bool = False,
    ) -> str:
        """
        Store a memory with its embedding.
        Returns the memory id (UUID string).
        Skips storage if a very similar active memory already exists
        (cosine similarity > 0.95) unless force=True.
        """
        embedding = get_embedding(content)

        if not force:
            existing = self._active_with_embeddings()
            for row in existing:
                sim = cosine_similarity(embedding, json.loads(row["embedding"]))
                if sim > 0.95:
                    return row["id"]

        now = time.time()
        mem_id = str(uuid.uuid4())

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO memories
                   (id, type, valence, content, confidence, importance,
                    source, usage_count, status, created_at, updated_at,
                    last_accessed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, NULL)""",
                (mem_id, memory_type, valence, content, confidence,
                 importance, source, status, now, now),
            )
            conn.execute(
                "INSERT INTO embeddings (id, memory_id, embedding) VALUES (?, ?, ?)",
                (str(uuid.uuid4()), mem_id, json.dumps(embedding)),
            )
            conn.commit()

        return mem_id

    def search(self, query: str, top_k: int = 5) -> list[str]:
        """
        Return the top_k most semantically similar active memory contents.
        Updates usage_count and last_accessed_at on every match.
        """
        query_embedding = get_embedding(query)
        rows = self._active_with_embeddings()

        if not rows:
            return []

        scored = [
            (
                cosine_similarity(query_embedding, json.loads(row["embedding"])),
                row["content"],
                row["id"],
            )
            for row in rows
        ]
        scored.sort(reverse=True, key=lambda x: x[0])
        top = scored[:top_k]

        now = time.time()
        with self._connect() as conn:
            conn.executemany(
                """UPDATE memories
                   SET usage_count = usage_count + 1,
                       last_accessed_at = ?,
                       updated_at = ?
                   WHERE id = ?""",
                [(now, now, r[2]) for r in top],
            )
            conn.commit()

        return [r[1] for r in top]

    def search_typed(
        self, query: str, memory_type: str, top_k: int = 1
    ) -> list[tuple[float, str, str]]:
        """
        Return (similarity, content, valence) for top_k active memories
        of the given type, ranked by cosine similarity to query.
        """
        query_embedding = get_embedding(query)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT m.content, m.valence, e.embedding
                   FROM memories m
                   JOIN embeddings e ON e.memory_id = m.id
                   WHERE m.status = 'active' AND m.type = ?""",
                (memory_type,),
            ).fetchall()

        if not rows:
            return []

        scored = [
            (cosine_similarity(query_embedding, json.loads(r["embedding"])),
             r["content"], r["valence"])
            for r in rows
        ]
        scored.sort(reverse=True, key=lambda x: x[0])
        return scored[:top_k]

    def get_all(self) -> list[dict]:
        """Return all memories as dicts (embedding excluded)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, type, valence, content, confidence, importance,
                          source, usage_count, status,
                          created_at, updated_at, last_accessed_at
                   FROM memories"""
            ).fetchall()
        return [dict(r) for r in rows]

    def _active_with_embeddings(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """SELECT m.id, m.content, e.embedding
                   FROM memories m
                   JOIN embeddings e ON e.memory_id = m.id
                   WHERE m.status = 'active'"""
            ).fetchall()

    def get_active_full(self) -> list[dict]:
        """Return all active/disputed memories with full metadata and raw embedding JSON."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT m.id, m.type, m.valence, m.content,
                          m.confidence, m.importance,
                          m.last_accessed_at, e.embedding
                   FROM memories m
                   JOIN embeddings e ON e.memory_id = m.id
                   WHERE m.status IN ('active', 'disputed')"""
            ).fetchall()
        return [dict(r) for r in rows]

    def touch_many(self, memory_ids: list[str]) -> None:
        """Increment usage_count and refresh last_accessed_at for the given ids."""
        if not memory_ids:
            return
        now = time.time()
        with self._connect() as conn:
            conn.executemany(
                """UPDATE memories
                   SET usage_count = usage_count + 1,
                       last_accessed_at = ?,
                       updated_at = ?
                   WHERE id = ?""",
                [(now, now, mid) for mid in memory_ids],
            )
            conn.commit()

    def delete(self, memory_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM memories WHERE status = 'active'"
            ).fetchone()[0]
