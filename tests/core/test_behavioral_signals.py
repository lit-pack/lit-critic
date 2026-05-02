"""Tests for Phase E behavioral signal functions in core.service.

Covers:
- extract_behavioral_signals (E1): silenced findings → preferences,
  resolved findings → resolutions, persistent active findings → blind spots.
- build_silence_rule_preferences (E2): pattern/category silence rules →
  preference learning entries with appropriate confidence.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from core.domain import AnalysisSnapshot, SnapshotFinding
from core.service import build_silence_rule_preferences, extract_behavioral_signals
from orchestrator.persistence.database import init_db
from orchestrator.persistence.snapshot_store import SnapshotStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    """Open an in-memory SQLite connection with the full project schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _make_finding(**kwargs) -> SnapshotFinding:
    """Return a SnapshotFinding with sensible defaults."""
    defaults = dict(
        number=1,
        severity="major",
        lens="prose",
        location="paragraph 1",
        line_start=5,
        line_end=7,
        scene_path="text/ch1.txt",
        evidence="Repeated sentence starts undermine rhythm.",
        impact="Monotony",
        options=["Vary openings"],
        flagged_by=["prose"],
        ambiguity_type=None,
        state="active",
        correlation_key=None,
    )
    defaults.update(kwargs)
    f = SnapshotFinding(**defaults)
    if not f.correlation_key:
        f.correlation_key = SnapshotFinding.build_correlation_key(
            f.scene_path, f.lens, f.line_start, f.evidence
        )
    return f


def _make_snapshot(findings: list[SnapshotFinding], **kwargs) -> AnalysisSnapshot:
    """Return an AnalysisSnapshot with sensible defaults."""
    defaults = dict(
        scene_paths=["text/ch1.txt"],
        depth_mode="quick",
        frontier_model="",
        checker_model="",
        quick_model="haiku",
        scene_hashes={"text/ch1.txt": "abc123"},
        index_context_hash="",
        created_at=datetime.now().isoformat(),
    )
    defaults.update(kwargs)
    snap = AnalysisSnapshot(findings=findings, **defaults)
    return snap


def _learning_entries(conn: sqlite3.Connection) -> list[dict]:
    """Return all learning_entry rows as plain dicts."""
    rows = conn.execute("SELECT * FROM learning_entry ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _entries_by_category(conn: sqlite3.Connection, category: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM learning_entry WHERE category = ? ORDER BY id",
        (category,),
    ).fetchall()
    return [dict(r) for r in rows]


# ===========================================================================
# extract_behavioral_signals — silenced findings → preferences
# ===========================================================================

def test_silenced_finding_creates_preference_entry():
    """A silenced finding in the snapshot produces one preference learning entry."""
    conn = _conn()
    finding = _make_finding(state="silenced")
    snap = _make_snapshot([finding])
    SnapshotStore.create(conn, snap)

    counts = extract_behavioral_signals(conn, snap)

    prefs = _entries_by_category(conn, "preference")
    assert counts["preferences"] == 1
    assert len(prefs) == 1
    assert "[prose] major:" in prefs[0]["description"]
    assert float(prefs[0]["confidence"]) == pytest.approx(0.5)


def test_silenced_finding_escalates_confidence_on_repeat():
    """Calling extract_behavioral_signals twice on the same silenced finding
    escalates the existing entry's confidence instead of duplicating it."""
    conn = _conn()
    finding = _make_finding(state="silenced")

    # First run — creates entry at confidence 0.5.
    snap1 = _make_snapshot([finding])
    SnapshotStore.create(conn, snap1)
    counts1 = extract_behavioral_signals(conn, snap1)
    assert counts1["preferences"] == 1

    # Second run — same description → escalate to 0.7.
    snap2 = _make_snapshot([finding], scene_hashes={"text/ch1.txt": "def456"})
    SnapshotStore.create(conn, snap2)
    counts2 = extract_behavioral_signals(conn, snap2)

    # No new entry should be created.
    prefs = _entries_by_category(conn, "preference")
    assert counts2["preferences"] == 0   # entry already existed
    assert len(prefs) == 1
    assert float(prefs[0]["confidence"]) == pytest.approx(0.7)


def test_active_finding_does_not_create_preference():
    """An active (unsilenced) finding must NOT produce a preference entry."""
    conn = _conn()
    finding = _make_finding(state="active")
    snap = _make_snapshot([finding])
    SnapshotStore.create(conn, snap)

    counts = extract_behavioral_signals(conn, snap)

    assert counts["preferences"] == 0
    assert len(_entries_by_category(conn, "preference")) == 0


# ===========================================================================
# extract_behavioral_signals — resolved findings → resolutions
# ===========================================================================

def test_resolved_finding_in_previous_snapshot_creates_resolution():
    """A finding marked 'resolved' in the previous snapshot yields a resolution entry."""
    conn = _conn()

    # Snapshot 1: active finding.
    finding = _make_finding(state="active")
    snap1 = _make_snapshot([finding])
    SnapshotStore.create(conn, snap1)

    # Manually mark the finding as resolved (simulating what the correlation
    # service does when the underlying text changes between runs).
    conn.execute(
        "UPDATE snapshot_finding SET state = 'resolved' WHERE snapshot_id = ?",
        (snap1.id,),
    )
    conn.commit()

    # Snapshot 2: no findings (the problem was fixed).
    snap2 = _make_snapshot([], scene_hashes={"text/ch1.txt": "xyz999"})
    SnapshotStore.create(conn, snap2)

    counts = extract_behavioral_signals(conn, snap2)

    resolutions = _entries_by_category(conn, "resolution")
    assert counts["resolutions"] == 1
    assert len(resolutions) == 1
    assert "prose" in resolutions[0]["description"]
    assert "resolved" in resolutions[0]["description"]


def test_no_resolution_when_no_previous_snapshot():
    """When there is no previous snapshot for the scene, zero resolutions are created."""
    conn = _conn()
    snap = _make_snapshot([])
    SnapshotStore.create(conn, snap)

    counts = extract_behavioral_signals(conn, snap)

    assert counts["resolutions"] == 0


# ===========================================================================
# extract_behavioral_signals — persistent findings → blind spots
# ===========================================================================

def test_persistent_finding_creates_blind_spot_at_threshold():
    """A finding that appears as active in 3+ distinct snapshots is recorded as a blind spot."""
    conn = _conn()
    ckey = "prose::5::Repeated sentence starts undermine rhythm."
    finding = _make_finding(state="active", correlation_key=ckey)

    for i in range(3):
        snap = _make_snapshot([finding], scene_hashes={"text/ch1.txt": f"hash{i}"})
        SnapshotStore.create(conn, snap)

    # Run signal extraction on the 3rd snapshot.
    counts = extract_behavioral_signals(conn, snap, persistent_run_threshold=3)

    blind_spots = _entries_by_category(conn, "blind_spot")
    assert counts["blind_spots"] == 1
    assert len(blind_spots) == 1
    assert "prose" in blind_spots[0]["description"]
    assert "persistent" in blind_spots[0]["description"]


def test_finding_below_threshold_does_not_create_blind_spot():
    """A finding appearing in fewer runs than the threshold is NOT a blind spot."""
    conn = _conn()
    ckey = "prose::5::Repeated sentence starts undermine rhythm."
    finding = _make_finding(state="active", correlation_key=ckey)

    for i in range(2):  # only 2 runs, threshold is 3
        snap = _make_snapshot([finding], scene_hashes={"text/ch1.txt": f"hash{i}"})
        SnapshotStore.create(conn, snap)

    counts = extract_behavioral_signals(conn, snap, persistent_run_threshold=3)

    assert counts["blind_spots"] == 0
    assert len(_entries_by_category(conn, "blind_spot")) == 0


def test_blind_spot_not_duplicated_on_subsequent_runs():
    """Once a blind spot entry exists, subsequent calls don't create duplicates."""
    conn = _conn()
    ckey = "prose::5::Repeated sentence starts undermine rhythm."
    finding = _make_finding(state="active", correlation_key=ckey)

    for i in range(4):
        snap = _make_snapshot([finding], scene_hashes={"text/ch1.txt": f"hash{i}"})
        SnapshotStore.create(conn, snap)
        extract_behavioral_signals(conn, snap, persistent_run_threshold=3)

    # Should still have exactly one blind spot entry.
    blind_spots = _entries_by_category(conn, "blind_spot")
    assert len(blind_spots) == 1


def test_returns_zero_counts_when_snapshot_has_no_id():
    """extract_behavioral_signals is a no-op when snapshot.id is None."""
    conn = _conn()
    snap = _make_snapshot([_make_finding(state="silenced")])
    # Do NOT persist — id remains None.
    assert snap.id is None

    counts = extract_behavioral_signals(conn, snap)

    assert counts == {"preferences": 0, "resolutions": 0, "blind_spots": 0}
    assert len(_learning_entries(conn)) == 0


# ===========================================================================
# build_silence_rule_preferences (E2)
# ===========================================================================

def _insert_silence_rule(
    conn: sqlite3.Connection,
    rule_type: str,
    scope: str = "project",
    lens: str = "prose",
    severity: str = "any",
    text_pattern: str = "",
    note: str = "",
    suspended: int = 0,
) -> None:
    """Insert a silence_rule row directly (bypasses service layer)."""
    conn.execute(
        """INSERT INTO silence_rule
           (rule_type, scope, scene_path, finding_id, lens, severity, text_pattern,
            note, suspended, created_at)
           VALUES (?, ?, '', NULL, ?, ?, ?, ?, ?, ?)""",
        (rule_type, scope, lens, severity, text_pattern, note, suspended, datetime.now().isoformat()),
    )
    conn.commit()


def test_pattern_rule_creates_preference_with_point_seven_confidence():
    """A non-suspended 'pattern' rule produces a preference entry at confidence 0.7."""
    conn = _conn()
    _insert_silence_rule(conn, "pattern", note="dialect in dialogue is intentional")

    counts = build_silence_rule_preferences(conn)

    prefs = _entries_by_category(conn, "preference")
    assert counts["preferences_added"] == 1
    assert len(prefs) == 1
    assert "[POLICY] silence pattern" in prefs[0]["description"]
    assert float(prefs[0]["confidence"]) == pytest.approx(0.7)


def test_category_rule_creates_preference_with_point_nine_confidence():
    """A non-suspended 'category' rule produces a preference entry at confidence 0.9."""
    conn = _conn()
    _insert_silence_rule(conn, "category", lens="pacing")

    counts = build_silence_rule_preferences(conn)

    prefs = _entries_by_category(conn, "preference")
    assert counts["preferences_added"] == 1
    assert float(prefs[0]["confidence"]) == pytest.approx(0.9)
    assert "pacing" in prefs[0]["description"]


def test_instance_rule_is_not_converted():
    """Instance rules are too specific and must NOT produce preference entries."""
    conn = _conn()
    _insert_silence_rule(conn, "instance")

    counts = build_silence_rule_preferences(conn)

    assert counts["preferences_added"] == 0
    assert len(_entries_by_category(conn, "preference")) == 0


def test_suspended_rule_is_not_converted():
    """Suspended rules must NOT produce preference entries."""
    conn = _conn()
    _insert_silence_rule(conn, "pattern", suspended=1, note="suspended for now")

    counts = build_silence_rule_preferences(conn)

    assert counts["preferences_added"] == 0
    assert len(_entries_by_category(conn, "preference")) == 0


def test_existing_entry_confidence_escalated_if_lower():
    """When a matching entry already exists with lower confidence, it is escalated."""
    conn = _conn()
    _insert_silence_rule(conn, "pattern", note="my pattern note")

    # First call — creates entry at 0.7.
    build_silence_rule_preferences(conn)
    prefs_after_first = _entries_by_category(conn, "preference")
    assert float(prefs_after_first[0]["confidence"]) == pytest.approx(0.7)

    # Manually lower the confidence to simulate a stale entry.
    conn.execute(
        "UPDATE learning_entry SET confidence = 0.5 WHERE category = 'preference'",
    )
    conn.commit()

    # Second call — should escalate back to 0.7 (pattern rule confidence).
    counts = build_silence_rule_preferences(conn)

    prefs_after_second = _entries_by_category(conn, "preference")
    assert counts["preferences_updated"] == 1
    assert float(prefs_after_second[0]["confidence"]) == pytest.approx(0.7)


def test_no_rules_returns_zero_counts():
    """When there are no pattern/category rules, both counts are zero."""
    conn = _conn()

    counts = build_silence_rule_preferences(conn)

    assert counts == {"preferences_added": 0, "preferences_updated": 0}
    assert len(_entries_by_category(conn, "preference")) == 0
