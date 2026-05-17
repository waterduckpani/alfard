"""SQLite vector store — stores facts with embeddings and
tags for semantic retrieval. No external vector DB needed."""

import sqlite3
import json
import time
from pathlib import Path
from alfard.memory.embedder import get_embedding, cosine_similarity


class VectorStore:
    """
    Lightweight SQLite-based vector store for agent memories.
    Stores facts, their embeddings, and tags.
    Retrieves semantically similar facts using cosine similarity.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact        TEXT NOT NULL,
                    embedding   TEXT NOT NULL,
                    tags        TEXT NOT NULL DEFAULT '[]',
                    created_at  REAL NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.commit()

    def store(self, fact: str, tags: list[str] | None = None) -> int:
        """
        Store a fact with its embedding.
        Returns the row id.
        Skips storage if a very similar fact already exists (similarity > 0.95).
        """
        embedding = get_embedding(fact)

        # Deduplication check
        existing = self.get_all()
        for row in existing:
            sim = cosine_similarity(embedding, json.loads(row["embedding"]))
            if sim > 0.95:
                return row["id"]  # already stored

        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO facts (fact, embedding, tags, created_at)
                   VALUES (?, ?, ?, ?)""",
                (fact, json.dumps(embedding),
                 json.dumps(tags or []), time.time())
            )
            conn.commit()
            return cur.lastrowid

    def search(self, query: str, top_k: int = 5) -> list[str]:
        """
        Find the top_k most semantically similar facts to the query.
        Returns list of fact strings.
        """
        query_embedding = get_embedding(query)
        rows = self.get_all()

        if not rows:
            return []

        scored = []
        for row in rows:
            sim = cosine_similarity(
                query_embedding, json.loads(row["embedding"])
            )
            scored.append((sim, row["fact"], row["id"]))

        scored.sort(reverse=True, key=lambda x: x[0])
        top = scored[:top_k]

        # Update access counts
        ids = [r[2] for r in top]
        with self._connect() as conn:
            conn.executemany(
                "UPDATE facts SET access_count = access_count + 1 WHERE id = ?",
                [(i,) for i in ids]
            )
            conn.commit()

        return [r[1] for r in top]

    def get_all(self) -> list[dict]:
        """Return all stored facts as dicts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, fact, embedding, tags, created_at, access_count FROM facts"
            ).fetchall()
        return [
            {
                "id": r[0], "fact": r[1], "embedding": r[2],
                "tags": r[3], "created_at": r[4], "access_count": r[5]
            }
            for r in rows
        ]

    def delete(self, fact_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            conn.commit()

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
