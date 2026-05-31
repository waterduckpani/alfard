"""Cron run registry — persists cron job output message IDs so channel bots
can route thread replies back to the correct job context."""

import sqlite3
from alfard.cron.scheduler import CRON_DB

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        CRON_DB.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(CRON_DB), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS cron_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name    TEXT NOT NULL,
                agent_name  TEXT NOT NULL,
                run_ts      TEXT NOT NULL,
                channel     TEXT NOT NULL,
                message_id  TEXT NOT NULL,
                thread_id   TEXT,
                task        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'completed',
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        _conn.commit()
    return _conn


# Ensure the table exists on import.
_get_conn()


def register_run(
    job_name: str,
    agent_name: str,
    run_ts: str,
    channel: str,
    message_id: str,
    task: str,
    thread_id: str | None = None,
    status: str = "completed",
) -> int:
    """Insert a cron run row and return the new id."""
    conn = _get_conn()
    cur = conn.execute(
        """
        INSERT INTO cron_runs
            (job_name, agent_name, run_ts, channel, message_id, thread_id, task, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (job_name, agent_name, run_ts, channel, message_id, thread_id, task, status),
    )
    conn.commit()
    return cur.lastrowid


def lookup_run(channel: str, message_id: str) -> dict | None:
    """Return the run row matching (channel, message_id), or None."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT * FROM cron_runs WHERE channel = ? AND message_id = ? LIMIT 1",
        (channel, message_id),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([d[0] for d in cur.description], row))


def lookup_run_by_thread(channel: str, thread_id: str) -> dict | None:
    """Return the run row matching (channel, thread_id), or None."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT * FROM cron_runs WHERE channel = ? AND thread_id = ? LIMIT 1",
        (channel, thread_id),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([d[0] for d in cur.description], row))


def recent_runs(agent_name: str, limit: int = 20) -> list[dict]:
    """Return the most recent runs for an agent, newest first."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT * FROM cron_runs WHERE agent_name = ? ORDER BY id DESC LIMIT ?",
        (agent_name, limit),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
