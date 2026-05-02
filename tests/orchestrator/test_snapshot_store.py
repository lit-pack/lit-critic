"""Tests for AnalysisSnapshot / SnapshotFinding models and SnapshotStore (Task C1)."""

import sqlite3

from core.domain import AnalysisSnapshot, SnapshotFinding, FINDING_STATES
from orchestrator.persistence.database import init_db
from orchestrator.persistence.snapshot_store import SnapshotStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _make_snapshot(**kwargs) -> AnalysisSnapshot:
    defaults = dict(
        scene_paths=["text/ch1.md"],
        depth_mode="quick",
        frontier_model="",
        checker_model="gpt-4o-mini",
        quick_model="gpt-4o-mini",
        scene_hashes={"text/ch1.md": "abc123"},
        index_context_hash="idx001",
        created_at="2026-04-13T10:00:00",
    )
    defaults.update(kwargs)
    return AnalysisSnapshot(**defaults)


def _make_finding(**kwargs) -> SnapshotFinding:
    defaults = dict(
        number=1,
        severity="moderate",
        lens="prose",
        location="paragraph 3",
        line_start=10,
        line_end=12,
        scene_path="text/ch1.md",
        evidence="The sentence is too long.",
        impact="Reduces clarity.",
        options=["Break into two sentences", "Use semicolon"],
        flagged_by=["prose-lens"],
        state="active",
    )
    defaults.update(kwargs)
    return SnapshotFinding(**defaults)


# ---------------------------------------------------------------------------
# Domain model tests
# ---------------------------------------------------------------------------

def test_finding_states_constant():
    assert "active" in FINDING_STATES
    assert "silenced" in FINDING_STATES
    assert "resolved" in FINDING_STATES
    assert len(FINDING_STATES) == 3


def test_snapshot_finding_from_dict_round_trip():
    f = _make_finding()
    d = f.to_dict()
    f2 = SnapshotFinding.from_dict(d)
    assert f2.severity == f.severity
    assert f2.lens == f.lens
    assert f2.state == f.state
    assert f2.options == f.options


def test_analysis_snapshot_from_dict_round_trip():
    snap = _make_snapshot()
    snap.findings = [_make_finding(number=1), _make_finding(number=2, state="silenced")]
    d = snap.to_dict()
    snap2 = AnalysisSnapshot.from_dict(d)
    assert snap2.depth_mode == "quick"
    assert snap2.scene_paths == ["text/ch1.md"]
    assert len(snap2.findings) == 2


def test_analysis_snapshot_active_findings_filter():
    snap = _make_snapshot()
    snap.findings = [
        _make_finding(number=1, state="active"),
        _make_finding(number=2, state="silenced"),
        _make_finding(number=3, state="resolved"),
        _make_finding(number=4, state="active"),
    ]
    active = snap.active_findings
    assert len(active) == 2
    assert all(f.state == "active" for f in active)


def test_snapshot_finding_to_dict_no_id():
    f = _make_finding()
    d = f.to_dict()
    assert d["id"] is None
    assert d["snapshot_id"] is None
    assert d["state"] == "active"


def test_build_correlation_key_stability():
    key1 = SnapshotFinding.build_correlation_key("text/ch1.md", "prose", 10, "The sentence is too long.")
    key2 = SnapshotFinding.build_correlation_key("text/ch1.md", "prose", 10, "The sentence is too long.")
    assert key1 == key2


def test_build_correlation_key_differs_by_lens():
    key1 = SnapshotFinding.build_correlation_key("text/ch1.md", "prose", 10, "evidence")
    key2 = SnapshotFinding.build_correlation_key("text/ch1.md", "pacing", 10, "evidence")
    assert key1 != key2


def test_build_correlation_key_differs_by_location():
    key1 = SnapshotFinding.build_correlation_key("text/ch1.md", "prose", 10, "evidence")
    key2 = SnapshotFinding.build_correlation_key("text/ch1.md", "prose", 20, "evidence")
    assert key1 != key2


def test_build_correlation_key_none_line_start():
    # Should not raise; None treated as empty string.
    key = SnapshotFinding.build_correlation_key("text/ch1.md", "prose", None, "evidence")
    assert isinstance(key, str)
    assert len(key) > 0


# ---------------------------------------------------------------------------
# SnapshotStore persistence tests
# ---------------------------------------------------------------------------

def test_snapshot_store_create_and_get():
    conn = _conn()
    snap = _make_snapshot()
    snap.findings = [
        _make_finding(number=1),
        _make_finding(number=2, state="silenced", lens="pacing"),
    ]

    snap_id = SnapshotStore.create(conn, snap)
    assert snap_id is not None
    assert snap.id == snap_id
    # findings get back-filled ids
    assert snap.findings[0].id is not None
    assert snap.findings[1].snapshot_id == snap_id

    loaded = SnapshotStore.get(conn, snap_id)
    assert loaded is not None
    assert loaded.scene_paths == ["text/ch1.md"]
    assert loaded.depth_mode == "quick"
    assert loaded.scene_hashes == {"text/ch1.md": "abc123"}
    assert len(loaded.findings) == 2
    assert loaded.findings[0].state == "active"
    assert loaded.findings[1].state == "silenced"


def test_snapshot_store_create_no_findings():
    conn = _conn()
    snap = _make_snapshot()
    snap_id = SnapshotStore.create(conn, snap)
    loaded = SnapshotStore.get(conn, snap_id)
    assert loaded is not None
    assert loaded.findings == []


def test_snapshot_store_get_nonexistent():
    conn = _conn()
    result = SnapshotStore.get(conn, 9999)
    assert result is None


def test_snapshot_store_correlation_key_auto_set():
    """SnapshotStore.create fills correlation_key if not preset."""
    conn = _conn()
    snap = _make_snapshot()
    f = _make_finding(number=1)
    assert f.correlation_key == ""  # not set yet
    snap.findings = [f]

    SnapshotStore.create(conn, snap)

    loaded = SnapshotStore.get(conn, snap.id)
    assert loaded.findings[0].correlation_key != ""


def test_snapshot_store_get_latest_for_scene():
    conn = _conn()

    # Create two snapshots for the same scene (different timestamps).
    snap1 = _make_snapshot(created_at="2026-04-13T09:00:00")
    snap1.findings = [_make_finding(number=1, evidence="old finding")]
    SnapshotStore.create(conn, snap1)

    snap2 = _make_snapshot(created_at="2026-04-13T10:00:00")
    snap2.findings = [_make_finding(number=1, evidence="new finding")]
    SnapshotStore.create(conn, snap2)

    latest = SnapshotStore.get_latest_for_scene(conn, "text/ch1.md")
    assert latest is not None
    assert latest.id == snap2.id
    assert latest.findings[0].evidence == "new finding"


def test_snapshot_store_get_latest_for_scene_not_found():
    conn = _conn()
    result = SnapshotStore.get_latest_for_scene(conn, "text/missing.md")
    assert result is None


def test_snapshot_store_list_recent():
    conn = _conn()

    for i, ts in enumerate(
        ["2026-04-11T10:00:00", "2026-04-12T10:00:00", "2026-04-13T10:00:00"]
    ):
        snap = _make_snapshot(created_at=ts)
        snap.findings = [_make_finding(number=1)]
        SnapshotStore.create(conn, snap)

    recent = SnapshotStore.list_recent(conn, limit=2)
    assert len(recent) == 2
    # Most recent first.
    assert recent[0].created_at == "2026-04-13T10:00:00"
    assert recent[1].created_at == "2026-04-12T10:00:00"
    # list_recent does NOT load findings.
    assert recent[0].findings == []


def test_snapshot_store_update_finding_state():
    conn = _conn()
    snap = _make_snapshot()
    snap.findings = [_make_finding(number=1, state="active")]
    SnapshotStore.create(conn, snap)

    finding_id = snap.findings[0].id
    SnapshotStore.update_finding_state(conn, finding_id, "silenced")

    loaded = SnapshotStore.get(conn, snap.id)
    assert loaded.findings[0].state == "silenced"


def test_snapshot_store_get_finding():
    conn = _conn()
    snap = _make_snapshot()
    snap.findings = [_make_finding(number=1, lens="structure")]
    SnapshotStore.create(conn, snap)

    fid = snap.findings[0].id
    f = SnapshotStore.get_finding(conn, fid)
    assert f is not None
    assert f.lens == "structure"
    assert f.snapshot_id == snap.id


def test_snapshot_store_get_finding_nonexistent():
    conn = _conn()
    result = SnapshotStore.get_finding(conn, 99999)
    assert result is None


def test_snapshot_store_cascade_delete():
    """Deleting a snapshot via raw SQL removes its findings (ON DELETE CASCADE)."""
    conn = _conn()
    snap = _make_snapshot()
    snap.findings = [_make_finding(number=1)]
    SnapshotStore.create(conn, snap)
    snap_id = snap.id

    # Enable FK enforcement on this in-memory connection.
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("DELETE FROM analysis_snapshot WHERE id = ?", (snap_id,))
    conn.commit()

    remaining = conn.execute(
        "SELECT COUNT(*) FROM snapshot_finding WHERE snapshot_id = ?", (snap_id,)
    ).fetchone()[0]
    assert remaining == 0


def test_snapshot_store_delete_by_id_removes_snapshot_and_findings():
    conn = _conn()
    snap = _make_snapshot()
    snap.findings = [_make_finding(number=1), _make_finding(number=2)]
    SnapshotStore.create(conn, snap)
    snap_id = snap.id

    result = SnapshotStore.delete_by_id(conn, snap_id)

    assert result is True
    assert SnapshotStore.get(conn, snap_id) is None
    remaining = conn.execute(
        "SELECT COUNT(*) FROM snapshot_finding WHERE snapshot_id = ?", (snap_id,)
    ).fetchone()[0]
    assert remaining == 0


def test_snapshot_store_delete_by_id_nonexistent_returns_false():
    conn = _conn()
    result = SnapshotStore.delete_by_id(conn, 99999)
    assert result is False


def test_snapshot_store_delete_all_removes_all_snapshots_and_findings():
    conn = _conn()
    for i in range(3):
        snap = _make_snapshot(created_at=f"2026-04-1{i+1}T10:00:00")
        snap.findings = [_make_finding(number=1)]
        SnapshotStore.create(conn, snap)

    count = SnapshotStore.delete_all(conn)

    assert count == 3
    assert SnapshotStore.list_recent(conn) == []
    remaining_findings = conn.execute(
        "SELECT COUNT(*) FROM snapshot_finding"
    ).fetchone()[0]
    assert remaining_findings == 0


def test_snapshot_store_delete_all_empty_returns_zero():
    conn = _conn()
    count = SnapshotStore.delete_all(conn)
    assert count == 0


# ---------------------------------------------------------------------------
# source_file_hash round-trip (Task 1.1 — loop-redesign-plan)
# ---------------------------------------------------------------------------

def test_source_file_hash_round_trip():
    """source_file_hash is persisted via create() and restored via get()."""
    conn = _conn()
    snap = _make_snapshot(source_file_hash="deadbeef12345678")
    snap.findings = [_make_finding()]
    sid = SnapshotStore.create(conn, snap)

    loaded = SnapshotStore.get(conn, sid)
    assert loaded is not None
    assert loaded.source_file_hash == "deadbeef12345678"


def test_source_file_hash_defaults_empty():
    """Snapshots created without source_file_hash default to empty string."""
    conn = _conn()
    snap = _make_snapshot()  # no source_file_hash kwarg
    sid = SnapshotStore.create(conn, snap)

    loaded = SnapshotStore.get(conn, sid)
    assert loaded is not None
    assert loaded.source_file_hash == ""


def test_source_file_hash_in_get_latest_for_scene():
    """source_file_hash survives round-trip through get_latest_for_scene()."""
    conn = _conn()
    snap = _make_snapshot(source_file_hash="cafebabe00000000")
    snap.findings = [_make_finding()]
    SnapshotStore.create(conn, snap)

    loaded = SnapshotStore.get_latest_for_scene(conn, "text/ch1.md")
    assert loaded is not None
    assert loaded.source_file_hash == "cafebabe00000000"


def test_source_file_hash_in_list_recent():
    """source_file_hash survives round-trip through list_recent()."""
    conn = _conn()
    snap = _make_snapshot(source_file_hash="1111222233334444")
    SnapshotStore.create(conn, snap)

    recent = SnapshotStore.list_recent(conn, limit=5)
    assert len(recent) == 1
    assert recent[0].source_file_hash == "1111222233334444"


def test_source_file_hash_from_dict_to_dict():
    """source_file_hash survives AnalysisSnapshot from_dict/to_dict cycle."""
    snap = _make_snapshot(source_file_hash="abcdef0123456789")
    d = snap.to_dict()
    assert d["source_file_hash"] == "abcdef0123456789"

    restored = AnalysisSnapshot.from_dict(d)
    assert restored.source_file_hash == "abcdef0123456789"
