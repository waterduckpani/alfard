"""Test suite for MemoryManager and VectorStore.

Each test spins up a fresh MemoryManager in a tmp_path-isolated agent dir.
All embedding API calls are monkeypatched to a deterministic local function.
"""
import json
import time
import hashlib
import pytest
from unittest.mock import MagicMock

from alfard.memory.manager import MemoryManager


# ── Deterministic embedding mock ──────────────────────────────────────────────

def _hash_embed(text: str) -> list[float]:
    """Return a reproducible 16-dim unit vector from MD5 of text.

    Same text  → identical vector  → cosine_similarity = 1.0
    Diff texts → different vectors → similarity << 0.80 in practice
    """
    h = hashlib.md5(text.encode()).digest()
    v = [(b - 127.5) for b in h]
    norm = sum(x ** 2 for x in v) ** 0.5
    return [x / norm for x in v] if norm > 0 else [1.0] + [0.0] * 15


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mm(tmp_path, monkeypatch):
    """MemoryManager with all embedding calls mocked to avoid API calls."""
    monkeypatch.setattr("alfard.memory.store.get_embedding", _hash_embed)
    monkeypatch.setattr("alfard.memory.manager.get_embedding", _hash_embed)
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    return MemoryManager(agent_dir)


# ── WRITES ────────────────────────────────────────────────────────────────────

def test_user_explicit_write_defaults(mm):
    result = mm.write("user prefers dark mode", source="user_explicit")

    assert result.startswith("remembered:")
    rows = mm.brain_db.get_all()
    assert len(rows) == 1
    assert rows[0]["confidence"] == 1.0
    assert rows[0]["importance"] == 1.0


def test_agent_inferred_write_defaults(mm):
    result = mm.write("agent noticed slow response times", source="agent_inferred")

    assert result.startswith("remembered:")
    rows = mm.brain_db.get_all()
    assert len(rows) == 1
    assert rows[0]["confidence"] == 0.5
    assert rows[0]["importance"] == 0.5


def test_duplicate_skipped(mm):
    mm.write("the project uses Python 3.12", memory_type="fact")
    result = mm.write("the project uses Python 3.12", memory_type="fact")

    assert result == "duplicate"
    assert mm.brain_db.count() == 1


def test_conflict_creates_disputed_entry(mm):
    mm.write("the API is reliable", memory_type="fact", valence="positive")
    result = mm.write("the API is reliable", memory_type="fact", valence="negative")

    assert result == "conflict"
    all_mems = mm.brain_db.get_all()
    assert len(all_mems) == 2
    disputed = [m for m in all_mems if m["status"] == "disputed"]
    assert len(disputed) >= 1


def test_secret_sk_prefix_blocked(mm):
    result = mm.write("my key is sk-abcdefghijklmnopqrstuvwxyz123")
    assert result.startswith("blocked:")


def test_secret_password_blocked(mm):
    result = mm.write("database config: password=SuperSecret99")
    assert result.startswith("blocked:")


def test_secret_akia_blocked(mm):
    result = mm.write("AWS access key AKIAIOSFODNN7EXAMPLE is in use")
    assert result.startswith("blocked:")


def test_brain_md_regenerates_after_write(mm):
    brain_md = mm.agent_dir / "brain.md"
    assert not brain_md.exists()

    mm.write("deployments run on Kubernetes", memory_type="fact")

    assert brain_md.exists()
    content = brain_md.read_text()
    assert "deployments run on Kubernetes" in content


# ── RETRIEVAL ─────────────────────────────────────────────────────────────────

def test_negative_valence_scores_1_5x_higher(mm):
    # Same content, different types — dedup gate requires type AND valence to match,
    # so both writes succeed through the normal public path without force=True.
    mm.write("the server is flaky under load", memory_type="fact", valence="positive")
    mm.write("the server is flaky under load", memory_type="preference", valence="negative")

    results = mm.retrieve("the server is flaky under load", top_k=10)
    assert len(results) == 2

    positive_score = next(r["score"] for r in results if r["valence"] == "positive")
    negative_score = next(r["score"] for r in results if r["valence"] == "negative")

    assert negative_score == pytest.approx(positive_score * 1.5, rel=1e-3)


def test_project_state_always_scores_1_0(mm):
    mm.write("feature branch under review", memory_type="project_state")
    results = mm.retrieve("completely unrelated query xyz 12345", top_k=5)

    ps = [r for r in results if r["type"] == "project_state"]
    assert ps, "project_state memory should appear in results"
    assert ps[0]["score"] == 1.0


def test_retrieve_increments_usage_count_and_last_accessed(mm):
    mm.write("deployment runs on port 8080", memory_type="fact")
    row_before = mm.brain_db.get_all()[0]
    assert row_before["usage_count"] == 0
    assert row_before["last_accessed_at"] is None

    mm.retrieve("port 8080", top_k=5)

    row_after = mm.brain_db.get_all()[0]
    assert row_after["usage_count"] == 1
    assert row_after["last_accessed_at"] is not None


# ── GOAL LIFECYCLE ────────────────────────────────────────────────────────────

def test_complete_goal_marks_correct_goal(mm):
    mm.write("finish the authentication module", memory_type="goal")
    mm.write("write unit tests for billing", memory_type="goal")

    completed = mm.complete_goal("finish the authentication module")

    assert completed == "finish the authentication module"
    rows = {r["content"]: r["status"] for r in mm.brain_db.get_all()}
    assert rows["finish the authentication module"] == "complete"
    assert rows["write unit tests for billing"] == "active"


def test_mark_stale_goals(mm):
    now = time.time()
    # Insert 16 sessions directly, spaced 1 h apart (oldest first)
    for i in range(16):
        ts = now - (16 - i) * 3600
        with mm._connect_sessions() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (id, summary, topics, turn_count, outcome, created_at, embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (f"sess-{i}", f"summary {i}", "[]", 1, "ok", ts,
                 json.dumps([0.1] * 16)),
            )
            conn.commit()

    threshold = mm._session_threshold(15)
    assert threshold is not None

    # Write a goal and backdate last_accessed_at to before the threshold
    mm.write("deploy new version to staging", memory_type="goal")
    goal_id = mm.brain_db.get_all()[0]["id"]
    with mm.brain_db._connect() as conn:
        conn.execute(
            "UPDATE memories SET last_accessed_at = ? WHERE id = ?",
            (threshold - 100, goal_id),
        )
        conn.commit()

    stale_count = mm.mark_stale_goals(current_session_count=16)
    assert stale_count == 1
    assert mm.brain_db.get_all()[0]["status"] == "stale"


def test_archive_old_memories_archives_complete_goals_older_than_90_days(mm):
    mm.write("migrate auth to OAuth2", memory_type="goal")
    goal_id = mm.brain_db.get_all()[0]["id"]

    ninety_one_days_ago = time.time() - 91 * 24 * 3600
    with mm.brain_db._connect() as conn:
        conn.execute(
            "UPDATE memories SET status = 'complete', updated_at = ? WHERE id = ?",
            (ninety_one_days_ago, goal_id),
        )
        conn.commit()

    archived = mm.archive_old_memories()

    assert archived >= 1
    assert mm.brain_db.get_all()[0]["status"] == "archived"


# ── CAPS ──────────────────────────────────────────────────────────────────────

def test_type_cap_archives_lowest_scoring_excess(mm):
    cap = MemoryManager._TYPE_CAPS["project_state"]  # 10
    excess = 2
    for i in range(cap + excess):
        mm.write(f"project status checkpoint {i}", memory_type="project_state")

    assert mm.brain_db.count() == cap + excess

    archived = mm.enforce_caps()

    assert archived == excess
    with mm.brain_db._connect() as conn:
        active_ps = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status='active' AND type='project_state'"
        ).fetchone()[0]
    assert active_ps == cap


def test_overall_500_cap_enforced(mm):
    # "observation" is not in _TYPE_CAPS, so only the overall 500 cap applies.
    target = MemoryManager._OVERALL_CAP + 2  # 502
    for i in range(target):
        mm.brain_db.store(
            f"uncapped observation item {i}",
            memory_type="observation",
        )

    assert mm.brain_db.count() == target

    archived = mm.enforce_caps()

    assert archived == 2
    assert mm.brain_db.count() == MemoryManager._OVERALL_CAP


# ── REFLECT ───────────────────────────────────────────────────────────────────

def test_reflect_writes_proposals_when_session_count_is_multiple_of_10(mm, tmp_path):
    for i in range(10):
        mm.save_session(f"session summary {i}", ["deployment", "auth"], 3, "success")

    assert mm.get_session_count() == 10

    mock_llm = MagicMock()
    mock_llm.complete.return_value = {
        "content": (
            "TYPE: mistake\n"
            "VALENCE: negative\n"
            "CONTENT: Never skip input validation on upload endpoints\n"
            "REASON: Caused a data corruption bug in production\n"
            "---\n"
            "TYPE: procedure\n"
            "VALENCE: neutral\n"
            "CONTENT: Always run the full test suite before merging\n"
            "REASON: Catches regressions before they reach staging\n"
            "---"
        ),
        "tool_calls": None,
        "raw": None,
    }
    audit_log = tmp_path / "audit.log"

    count = mm.run_reflect(mock_llm, audit_log)

    assert count == 2
    proposals_path = mm.agent_dir / "memory" / "proposals.jsonl"
    assert proposals_path.exists()

    proposals = [json.loads(line) for line in proposals_path.read_text().splitlines()]
    assert len(proposals) == 2

    p0 = proposals[0]
    assert p0["type"] == "mistake"
    assert p0["valence"] == "negative"
    assert p0["content"] == "Never skip input validation on upload endpoints"
    assert p0["reason"] == "Caused a data corruption bug in production"
    assert p0["status"] == "pending"
    assert "proposed_at" in p0

    p1 = proposals[1]
    assert p1["type"] == "procedure"
    assert p1["content"] == "Always run the full test suite before merging"


def test_reflect_skips_when_session_count_not_multiple_of_10(mm, tmp_path):
    for i in range(11):
        mm.save_session(f"session {i}", ["topic"], 2, "ok")

    assert mm.get_session_count() == 11

    mock_llm = MagicMock()
    mock_llm.complete.return_value = {"content": "TYPE: fact\nCONTENT: x\n---",
                                       "tool_calls": None, "raw": None}

    count = mm.run_reflect(mock_llm, tmp_path / "audit.log")

    assert count == 0
    mock_llm.complete.assert_not_called()


def test_reflect_prompt_contains_summaries_and_mistakes(mm, tmp_path):
    """The prompt passed to the LLM must include session summaries and known mistakes."""
    for i in range(10):
        mm.save_session(f"deployed service version {i}", ["deploy"], 3, "success")
    mm.write("never deploy on Fridays", memory_type="mistake", valence="negative")

    mock_llm = MagicMock()
    mock_llm.complete.return_value = {"content": "", "tool_calls": None, "raw": None}

    mm.run_reflect(mock_llm, tmp_path / "audit.log")

    assert mock_llm.complete.called
    messages = mock_llm.complete.call_args[0][0]
    prompt = messages[0]["content"]
    assert "deployed service version" in prompt
    assert "never deploy on Fridays" in prompt


def test_reflect_skips_malformed_blocks_keeps_valid(mm, tmp_path):
    """Blocks missing CONTENT or missing TYPE are dropped; a valid block still survives."""
    for i in range(10):
        mm.save_session(f"session {i}", ["t"], 1, "ok")

    mock_llm = MagicMock()
    mock_llm.complete.return_value = {
        "content": (
            # Block 1: missing CONTENT — skipped
            "TYPE: fact\n"
            "VALENCE: neutral\n"
            "REASON: no content here\n"
            "---\n"
            # Block 2: missing TYPE — skipped
            "VALENCE: neutral\n"
            "CONTENT: a memory without a type\n"
            "REASON: orphan\n"
            "---\n"
            # Block 3: valid — must be written
            "TYPE: procedure\n"
            "VALENCE: neutral\n"
            "CONTENT: Run integration tests before merging\n"
            "REASON: catches regressions\n"
            "---"
        ),
        "tool_calls": None,
        "raw": None,
    }

    count = mm.run_reflect(mock_llm, tmp_path / "audit.log")

    assert count == 1
    proposals_path = mm.agent_dir / "memory" / "proposals.jsonl"
    proposals = [json.loads(line) for line in proposals_path.read_text().splitlines()]
    assert len(proposals) == 1
    assert proposals[0]["content"] == "Run integration tests before merging"


def test_reflect_rejects_invalid_type(mm, tmp_path):
    """A proposal whose TYPE is not in the known type list is dropped."""
    for i in range(10):
        mm.save_session(f"session {i}", ["t"], 1, "ok")

    mock_llm = MagicMock()
    mock_llm.complete.return_value = {
        "content": (
            "TYPE: unknowntype\n"
            "VALENCE: neutral\n"
            "CONTENT: Some dubious memory\n"
            "REASON: bad type\n"
            "---\n"
            "TYPE: fact\n"
            "VALENCE: neutral\n"
            "CONTENT: Valid fact entry\n"
            "REASON: good type\n"
            "---"
        ),
        "tool_calls": None,
        "raw": None,
    }

    count = mm.run_reflect(mock_llm, tmp_path / "audit.log")

    assert count == 1
    proposals_path = mm.agent_dir / "memory" / "proposals.jsonl"
    proposals = [json.loads(line) for line in proposals_path.read_text().splitlines()]
    assert proposals[0]["content"] == "Valid fact entry"


def test_reflect_rejects_invalid_valence(mm, tmp_path):
    """A proposal whose VALENCE is not positive/negative/neutral is dropped."""
    for i in range(10):
        mm.save_session(f"session {i}", ["t"], 1, "ok")

    mock_llm = MagicMock()
    mock_llm.complete.return_value = {
        "content": (
            "TYPE: fact\n"
            "VALENCE: very_bad\n"
            "CONTENT: Memory with bad valence\n"
            "REASON: should be rejected\n"
            "---\n"
            "TYPE: fact\n"
            "VALENCE: positive\n"
            "CONTENT: Memory with good valence\n"
            "REASON: should be accepted\n"
            "---"
        ),
        "tool_calls": None,
        "raw": None,
    }

    count = mm.run_reflect(mock_llm, tmp_path / "audit.log")

    assert count == 1
    proposals_path = mm.agent_dir / "memory" / "proposals.jsonl"
    proposals = [json.loads(line) for line in proposals_path.read_text().splitlines()]
    assert proposals[0]["content"] == "Memory with good valence"


def test_reflect_deduplicates_proposals(mm, tmp_path):
    """The same proposal content is not written to proposals.jsonl a second time."""
    for i in range(10):
        mm.save_session(f"session {i}", ["t"], 1, "ok")

    block = (
        "TYPE: procedure\n"
        "VALENCE: neutral\n"
        "CONTENT: Always write tests before merging\n"
        "REASON: prevents regressions\n"
        "---"
    )
    mock_llm = MagicMock()
    mock_llm.complete.return_value = {"content": block, "tool_calls": None, "raw": None}

    count1 = mm.run_reflect(mock_llm, tmp_path / "audit.log")
    assert count1 == 1

    # Advance to the next cycle (session count must be a non-zero multiple of 10)
    for i in range(10):
        mm.save_session(f"extra session {i}", ["t"], 1, "ok")

    count2 = mm.run_reflect(mock_llm, tmp_path / "audit.log")
    assert count2 == 0

    proposals_path = mm.agent_dir / "memory" / "proposals.jsonl"
    lines = proposals_path.read_text().splitlines()
    assert len(lines) == 1


def test_reflect_parses_session_end_events_from_audit_jsonl(mm, tmp_path):
    """session_end events in audit.jsonl are parsed and appear in the LLM prompt."""
    for i in range(10):
        mm.save_session(f"session {i}", ["t"], 1, "ok")

    audit_log = tmp_path / "audit.jsonl"
    events = [
        {"type": "tool_call", "tool": "bash", "ts": 1000},  # irrelevant row
        {"type": "session_end", "outcome": "failed",
         "tool_calls_failed": 3, "corrections_detected": 1, "turns": 7},
        {"type": "session_end", "outcome": "success",
         "tool_calls_failed": 0, "corrections_detected": 0, "turns": 4},
    ]
    audit_log.write_text("\n".join(json.dumps(e) for e in events))

    mock_llm = MagicMock()
    mock_llm.complete.return_value = {"content": "", "tool_calls": None, "raw": None}

    mm.run_reflect(mock_llm, audit_log)

    assert mock_llm.complete.called
    prompt = mock_llm.complete.call_args[0][0][0]["content"]
    assert "outcome=failed" in prompt
    assert "failed=3" in prompt
    assert "corrections=1" in prompt
    assert "turns=7" in prompt
    assert "outcome=success" in prompt
