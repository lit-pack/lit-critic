"""Tests for finding correlation service (Task C5)."""

import sqlite3

from core.domain import AnalysisSnapshot, SnapshotFinding
from orchestrator.persistence.database import init_db
from orchestrator.persistence.snapshot_store import SnapshotStore
from orchestrator.services.finding_correlation_service import (
    identify_resolved_findings,
    persist_resolved_findings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _make_finding(*, number: int, state: str = "active", evidence: str = "evidence A",
                  lens: str = "prose", line_start: int = 10,
                  scene_path: str = "text/ch1.md") -> SnapshotFinding:
    f = SnapshotFinding(
        number=number,
        severity="moderate",
        lens=lens,
        location="para 1",
        line_start=line_start,
        scene_path=scene_path,
        evidence=evidence,
        state=state,
    )
    # Build correlation_key immediately so tests can rely on it.
    f = SnapshotFinding.from_dict({
        **f.to_dict(),
        "correlation_key": SnapshotFinding.build_correlation_key(
            f.scene_path, f.lens, f.line_start, f.evidence
        ),
    })
    return f


def _save_snapshot(conn, findings: list[SnapshotFinding],
                   scene_path: str = "text/ch1.md",
                   scene_hash: str = "hash-v1",
                   created_at: str = "2026-04-13T09:00:00") -> AnalysisSnapshot:
    snap = AnalysisSnapshot(
        scene_paths=[scene_path],
        depth_mode="quick",
        scene_hashes={scene_path: scene_hash},
        created_at=created_at,
        findings=findings,
    )
    SnapshotStore.create(conn, snap)
    return snap


# ---------------------------------------------------------------------------
# identify_resolved_findings — pure function
# ---------------------------------------------------------------------------

def test_identify_resolved_when_missing():
    prev = [_make_finding(number=1, evidence="old")]
    new_f = [_make_finding(number=1, evidence="completely different")]
    resolved = identify_resolved_findings(prev, new_f)
    assert len(resolved) == 1
    assert resolved[0].evidence == "old"


def test_identify_no_resolved_when_all_present():
    findings = [_make_finding(number=1, evidence="same")]
    resolved = identify_resolved_findings(findings, findings)
    assert resolved == []


def test_identify_resolved_skips_already_resolved():
    prev = [_make_finding(number=1, state="resolved", evidence="already resolved")]
    resolved = identify_resolved_findings(prev, [])
    assert resolved == []


def test_identify_resolved_includes_silenced_missing():
    prev = [_make_finding(number=1, state="silenced", evidence="silenced but gone")]
    resolved = identify_resolved_findings(prev, [])
    assert len(resolved) == 1


# ---------------------------------------------------------------------------
# persist_resolved_findings — DB integration
# ---------------------------------------------------------------------------

def test_persist_resolved_writes_state():
    conn = _conn()
    snap = _save_snapshot(conn, [_make_finding(number=1)])
    loaded = SnapshotStore.get(conn, snap.id)
    finding = loaded.findings[0]
    assert finding.state == "active"

    persist_resolved_findings(conn, [finding])

    reloaded = SnapshotStore.get(conn, snap.id)
    assert reloaded.findings[0].state == "resolved"


def test_persist_resolved_skips_none_id():
    conn = _conn()
    no_id_finding = _make_finding(number=1)  # id=None
    # Should not raise
    persist_resolved_findings(conn, [no_id_finding])


