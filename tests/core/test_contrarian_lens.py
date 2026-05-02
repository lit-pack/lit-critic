"""Tests for Phase G — Contrarian Lens (core.service).

Covers:
- run_contrarian_lens: silenced lens → records silencing and returns empty;
  no patterns → returns empty; patterns present → calls LLM and returns findings;
  LLM failure → returns empty gracefully.
- _parse_contrarian_findings: JSON parsing, markdown fences, bad input.
- _gather_contrarian_patterns: threshold enforcement.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pytest

from core.service import (
    _CONTRARIAN_LENS_NAME,
    _CONTRARIAN_SILENCED_DESC,
    _gather_contrarian_patterns,
    _parse_contrarian_findings,
    run_contrarian_lens,
)
from orchestrator.persistence.database import init_db
from orchestrator.persistence.snapshot_store import SnapshotStore
from core.domain import AnalysisSnapshot, SnapshotFinding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _insert_silence_rule(
    conn: sqlite3.Connection,
    rule_type: str = "category",
    lens: str = "contrarian",
    suspended: int = 0,
) -> None:
    conn.execute(
        """INSERT INTO silence_rule
           (rule_type, scope, scene_path, finding_id, lens, severity,
            text_pattern, note, suspended, created_at)
           VALUES (?, 'project', '', NULL, ?, '', '', '', ?, ?)""",
        (rule_type, lens, suspended, datetime.now().isoformat()),
    )
    conn.commit()


def _insert_snapshot_with_active_finding(
    conn: sqlite3.Connection,
    lens: str = "prose",
    evidence: str = "Passive voice overuse",
    n_snapshots: int = 3,
    correlation_key: str = "prose::5::Passive voice overuse",
) -> None:
    """Insert N snapshots each containing one active finding with the same correlation_key."""
    for i in range(n_snapshots):
        snap = AnalysisSnapshot(
            scene_paths=["text/ch1.txt"],
            depth_mode="quick",
            frontier_model="",
            checker_model="",
            quick_model="haiku",
            scene_hashes={"text/ch1.txt": f"hash{i}"},
            index_context_hash="",
            created_at=datetime.now().isoformat(),
        )
        finding = SnapshotFinding(
            number=1,
            severity="major",
            lens=lens,
            location="paragraph 1",
            line_start=5,
            line_end=7,
            scene_path="text/ch1.txt",
            evidence=evidence,
            impact="Weak",
            options=[],
            flagged_by=[lens],
            ambiguity_type=None,
            state="active",
            correlation_key=correlation_key,
        )
        snap.findings = [finding]
        SnapshotStore.create(conn, snap)


class _FakeLLMClient:
    """LLM client stub that returns a fixed JSON response."""

    def __init__(self, response: str):
        self._response = response
        self.called = False
        self.last_messages: list | None = None

    async def create_message(self, **kwargs):
        self.called = True
        self.last_messages = kwargs.get("messages")
        _text = self._response  # capture before entering nested scope

        class _Resp:
            text = _text

        return _Resp()


class _FailingLLMClient:
    """LLM client stub that always raises."""

    async def create_message(self, **kwargs):
        raise RuntimeError("LLM unavailable")


# ===========================================================================
# run_contrarian_lens — silenced contrarian lens
# ===========================================================================

async def test_returns_empty_and_records_when_contrarian_lens_is_silenced():
    """When a category silence rule exists for the contrarian lens, returns []
    and writes a prominent preference entry."""
    conn = _conn()
    _insert_silence_rule(conn, rule_type="category", lens=_CONTRARIAN_LENS_NAME)
    client = _FakeLLMClient("[]")

    result = await run_contrarian_lens(conn, client, "frontier-model")

    assert result == []
    assert not client.called

    # Should have written the silencing record.
    row = conn.execute(
        "SELECT description, confidence FROM learning_entry "
        "WHERE category = 'preference' AND description = ?",
        (_CONTRARIAN_SILENCED_DESC,),
    ).fetchone()
    assert row is not None
    assert float(row["confidence"]) == pytest.approx(0.9)


async def test_silencing_record_not_duplicated_on_repeat_calls():
    """Calling run_contrarian_lens multiple times with a silenced lens does not
    create duplicate learning entries."""
    conn = _conn()
    _insert_silence_rule(conn, rule_type="category", lens=_CONTRARIAN_LENS_NAME)
    client = _FakeLLMClient("[]")

    await run_contrarian_lens(conn, client, "frontier-model")
    await run_contrarian_lens(conn, client, "frontier-model")

    rows = conn.execute(
        "SELECT count(*) AS c FROM learning_entry WHERE description = ?",
        (_CONTRARIAN_SILENCED_DESC,),
    ).fetchone()
    assert rows["c"] == 1


async def test_suspended_silence_rule_does_not_block_contrarian_lens():
    """A *suspended* category rule for the contrarian lens must NOT block it."""
    conn = _conn()
    _insert_silence_rule(conn, rule_type="category", lens=_CONTRARIAN_LENS_NAME, suspended=1)
    client = _FakeLLMClient("[]")

    result = await run_contrarian_lens(conn, client, "fm", min_pattern_count=1)

    # No patterns in DB → should return [] without calling LLM.
    assert result == []
    assert not client.called


# ===========================================================================
# run_contrarian_lens — no significant patterns
# ===========================================================================

async def test_returns_empty_when_no_significant_patterns():
    """When silence counts and persistent findings are both below the threshold,
    the LLM is not called and an empty list is returned."""
    conn = _conn()
    # Insert a finding that appears in only 1 snapshot (below default threshold of 3).
    _insert_snapshot_with_active_finding(conn, n_snapshots=1)
    client = _FakeLLMClient("[]")

    result = await run_contrarian_lens(conn, client, "fm", min_pattern_count=3)

    assert result == []
    assert not client.called


# ===========================================================================
# run_contrarian_lens — patterns present → LLM called
# ===========================================================================

async def test_calls_llm_when_patterns_are_present():
    """When persistent findings reach the threshold, the LLM is called."""
    conn = _conn()
    _insert_snapshot_with_active_finding(conn, n_snapshots=3)

    fake_response = json.dumps([
        {
            "severity": "major",
            "evidence": "Passive voice is consistently ignored across multiple scenes.",
            "impact": "Narration feels distant and weak.",
            "options": ["Rewrite passive constructions", "Audit each scene for verb choice"],
        }
    ])
    client = _FakeLLMClient(fake_response)

    result = await run_contrarian_lens(conn, client, "fm", min_pattern_count=3)

    assert client.called
    assert len(result) == 1
    assert result[0]["lens"] == _CONTRARIAN_LENS_NAME
    assert result[0]["severity"] == "major"
    assert "Passive voice" in result[0]["evidence"]
    assert result[0]["location"] == "[project-level]"
    assert result[0]["line_start"] is None


async def test_returns_empty_when_llm_fails():
    """A failing LLM client should not raise; run_contrarian_lens returns []."""
    conn = _conn()
    _insert_snapshot_with_active_finding(conn, n_snapshots=3)

    result = await run_contrarian_lens(conn, _FailingLLMClient(), "fm", min_pattern_count=3)

    assert result == []


async def test_returns_empty_when_llm_returns_malformed_json():
    """Malformed JSON from the LLM is handled gracefully."""
    conn = _conn()
    _insert_snapshot_with_active_finding(conn, n_snapshots=3)

    client = _FakeLLMClient("This is not JSON at all.")

    result = await run_contrarian_lens(conn, client, "fm", min_pattern_count=3)

    assert result == []


# ===========================================================================
# _parse_contrarian_findings
# ===========================================================================

def test_parse_valid_json_array():
    """A well-formed JSON array is parsed into finding dicts."""
    raw = json.dumps([
        {
            "severity": "critical",
            "evidence": "Pacing issues recur in every chapter.",
            "impact": "Reader loses momentum.",
            "options": ["Tighten Act 2", "Cut filler scenes"],
        }
    ])
    findings = _parse_contrarian_findings(raw)

    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"
    assert findings[0]["lens"] == _CONTRARIAN_LENS_NAME
    assert findings[0]["options"] == ["Tighten Act 2", "Cut filler scenes"]


def test_parse_strips_markdown_fences():
    """JSON wrapped in markdown code fences is still parsed correctly."""
    inner = json.dumps([
        {"severity": "minor", "evidence": "Dialogue is flat.", "impact": "Characters feel dull.", "options": []}
    ])
    raw = f"```json\n{inner}\n```"
    findings = _parse_contrarian_findings(raw)
    assert len(findings) == 1
    assert findings[0]["severity"] == "minor"


def test_parse_returns_empty_on_invalid_json():
    """Non-JSON text returns an empty list without raising."""
    assert _parse_contrarian_findings("not json") == []


def test_parse_returns_empty_on_empty_array():
    """An empty JSON array returns an empty list."""
    assert _parse_contrarian_findings("[]") == []


def test_parse_skips_findings_without_evidence():
    """Items missing an 'evidence' key are silently skipped."""
    raw = json.dumps([
        {"severity": "major", "impact": "big", "options": []},  # no evidence key
        {"severity": "minor", "evidence": "Real finding.", "impact": "some", "options": []},
    ])
    findings = _parse_contrarian_findings(raw)
    assert len(findings) == 1
    assert "Real finding" in findings[0]["evidence"]


def test_parse_normalizes_unknown_severity():
    """An unrecognised severity value is normalised to 'minor'."""
    raw = json.dumps([
        {"severity": "extreme", "evidence": "Some pattern.", "impact": "bad", "options": []}
    ])
    findings = _parse_contrarian_findings(raw)
    assert findings[0]["severity"] == "minor"


# ===========================================================================
# _gather_contrarian_patterns
# ===========================================================================

def test_gather_patterns_returns_persistent_findings_at_threshold():
    """Findings that appear in ≥ N distinct snapshots are returned."""
    conn = _conn()
    _insert_snapshot_with_active_finding(conn, n_snapshots=3)

    patterns = _gather_contrarian_patterns(conn, min_count=3)

    assert len(patterns["persistent_findings"]) == 1
    assert patterns["persistent_findings"][0]["run_count"] == 3


def test_gather_patterns_excludes_below_threshold():
    """Findings that appear in fewer than N snapshots are excluded."""
    conn = _conn()
    _insert_snapshot_with_active_finding(conn, n_snapshots=2)

    patterns = _gather_contrarian_patterns(conn, min_count=3)

    assert patterns["persistent_findings"] == []


def test_gather_patterns_returns_silence_counts_at_threshold():
    """Silence rules are counted by lens and returned when count ≥ threshold."""
    conn = _conn()
    for _ in range(4):
        conn.execute(
            """INSERT INTO silence_rule
               (rule_type, scope, scene_path, finding_id, lens, severity,
                text_pattern, note, suspended, created_at)
               VALUES ('instance', 'scene', '', NULL, 'pacing', '', '', '', 0, ?)""",
            (datetime.now().isoformat(),),
        )
    conn.commit()

    patterns = _gather_contrarian_patterns(conn, min_count=3)

    assert any(r["lens"] == "pacing" and r["count"] >= 3 for r in patterns["silence_by_lens"])


def test_gather_patterns_excludes_contrarian_lens_from_silence_count():
    """Silence rules for the contrarian lens itself must not appear in patterns."""
    conn = _conn()
    for _ in range(5):
        conn.execute(
            """INSERT INTO silence_rule
               (rule_type, scope, scene_path, finding_id, lens, severity,
                text_pattern, note, suspended, created_at)
               VALUES ('category', 'project', '', NULL, ?, '', '', '', 0, ?)""",
            (_CONTRARIAN_LENS_NAME, datetime.now().isoformat()),
        )
    conn.commit()

    patterns = _gather_contrarian_patterns(conn, min_count=3)

    assert not any(
        r["lens"] == _CONTRARIAN_LENS_NAME for r in patterns["silence_by_lens"]
    )
