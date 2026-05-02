"""Tests for snapshot analysis service (Task C6)."""

import sqlite3

from core.domain import AnalysisSnapshot, CoreFinding, SilenceRule, SnapshotFinding
from orchestrator.persistence.database import init_db
from orchestrator.persistence.snapshot_store import SnapshotStore
from orchestrator.services.silence_rule_service import create_rule
from orchestrator.services.snapshot_analysis_service import (
    core_finding_to_snapshot_finding,
    core_findings_to_snapshot_findings,
    create_snapshot_from_core_findings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _make_core_finding(*, number: int = 1, lens: str = "prose",
                        severity: str = "moderate",
                        location: str = "para 1",
                        evidence: str = "sentence is too long",
                        line_start: int = 10) -> CoreFinding:
    return CoreFinding(
        number=number,
        severity=severity,
        lens=lens,
        location=location,
        line_start=line_start,
        evidence=evidence,
        impact="reduces readability",
        options=["shorten sentence"],
        flagged_by=[lens],
    )


# ---------------------------------------------------------------------------
# core_finding_to_snapshot_finding
# ---------------------------------------------------------------------------

def test_conversion_preserves_fields():
    cf = _make_core_finding()
    sf = core_finding_to_snapshot_finding(cf, number=1, scene_path="text/ch1.md")
    assert sf.severity == cf.severity
    assert sf.lens == cf.lens
    assert sf.location == cf.location
    assert sf.evidence == cf.evidence
    assert sf.impact == cf.impact
    assert sf.options == cf.options
    assert sf.flagged_by == cf.flagged_by


def test_conversion_sets_state_active():
    cf = _make_core_finding(lens="prose")
    cf.status = "accepted"  # old-model status should be discarded
    sf = core_finding_to_snapshot_finding(cf, number=1, scene_path="text/ch1.md")
    assert sf.state == "active"


def test_conversion_sets_scene_path():
    cf = _make_core_finding()
    sf = core_finding_to_snapshot_finding(cf, number=1, scene_path="text/ch1.md")
    assert sf.scene_path == "text/ch1.md"


def test_conversion_sets_correlation_key():
    cf = _make_core_finding()
    sf = core_finding_to_snapshot_finding(cf, number=1, scene_path="text/ch1.md")
    assert sf.correlation_key != ""


def test_conversion_number_override():
    cf = _make_core_finding(number=3)
    sf = core_finding_to_snapshot_finding(cf, number=7, scene_path="text/ch1.md")
    assert sf.number == 7  # number param overrides CoreFinding.number


def test_core_findings_to_snapshot_findings_numbered_sequentially():
    findings = [_make_core_finding(number=i) for i in range(3)]
    result = core_findings_to_snapshot_findings(findings, scene_path="text/ch1.md")
    assert [f.number for f in result] == [1, 2, 3]


# ---------------------------------------------------------------------------
# create_snapshot_from_core_findings — basic persistence
# ---------------------------------------------------------------------------

def test_create_snapshot_persists_to_db():
    conn = _conn()
    cf = _make_core_finding()
    snap = create_snapshot_from_core_findings(
        conn,
        scene_paths=["text/ch1.md"],
        findings_by_scene={"text/ch1.md": [cf]},
        depth_mode="quick",
        scene_hashes={"text/ch1.md": "hash-abc"},
        created_at="2026-04-13T10:00:00",
        apply_silence=False,
    )
    assert snap.id is not None
    loaded = SnapshotStore.get(conn, snap.id)
    assert loaded is not None
    assert len(loaded.findings) == 1
    assert loaded.findings[0].lens == "prose"


def test_create_snapshot_sets_depth_mode():
    conn = _conn()
    snap = create_snapshot_from_core_findings(
        conn,
        scene_paths=["text/ch1.md"],
        findings_by_scene={"text/ch1.md": [_make_core_finding()]},
        depth_mode="deep",
        created_at="2026-04-13T10:00:00",
        apply_silence=False,
    )
    assert snap.depth_mode == "deep"


def test_create_snapshot_multi_scene():
    conn = _conn()
    snap = create_snapshot_from_core_findings(
        conn,
        scene_paths=["text/ch1.md", "text/ch2.md"],
        findings_by_scene={
            "text/ch1.md": [_make_core_finding(number=1, evidence="ch1 finding")],
            "text/ch2.md": [_make_core_finding(number=1, evidence="ch2 finding")],
        },
        depth_mode="quick",
        created_at="2026-04-13T10:00:00",
        apply_silence=False,
    )
    assert len(snap.findings) == 2
    scene_paths = {f.scene_path for f in snap.findings}
    assert "text/ch1.md" in scene_paths
    assert "text/ch2.md" in scene_paths


def test_create_snapshot_no_findings():
    conn = _conn()
    snap = create_snapshot_from_core_findings(
        conn,
        scene_paths=["text/ch1.md"],
        findings_by_scene={"text/ch1.md": []},
        depth_mode="quick",
        created_at="2026-04-13T10:00:00",
        apply_silence=False,
    )
    assert snap.id is not None
    assert snap.findings == []


def test_create_snapshot_uses_utc_timestamp_when_no_created_at():
    conn = _conn()
    snap = create_snapshot_from_core_findings(
        conn,
        scene_paths=["text/ch1.md"],
        findings_by_scene={},
        apply_silence=False,
    )
    assert snap.created_at != ""
    assert "T" in snap.created_at  # ISO-8601 format


# ---------------------------------------------------------------------------
# create_snapshot_from_core_findings — with silence rules
# ---------------------------------------------------------------------------

def test_create_snapshot_with_silence_rules_applied():
    """A category rule silences matching findings in the new snapshot."""
    conn = _conn()

    # Create a silence rule before analysis.
    rule = SilenceRule(
        rule_type="category",
        scope="project",
        lens="prose",
        created_at="2026-04-13T09:00:00",
    )
    create_rule(conn, rule)

    snap = create_snapshot_from_core_findings(
        conn,
        scene_paths=["text/ch1.md"],
        findings_by_scene={"text/ch1.md": [_make_core_finding(lens="prose")]},
        depth_mode="quick",
        created_at="2026-04-13T10:00:00",
        apply_silence=True,
    )

    # Finding should be silenced.
    assert snap.findings[0].state == "silenced"

    # And persisted as silenced in DB.
    reloaded = SnapshotStore.get(conn, snap.id)
    assert reloaded.findings[0].state == "silenced"


def test_create_snapshot_silence_only_matching_lens():
    """Silence rule for 'prose' should not silence 'pacing' findings."""
    conn = _conn()
    rule = SilenceRule(rule_type="category", scope="project", lens="prose",
                       created_at="2026-04-13T09:00:00")
    create_rule(conn, rule)

    snap = create_snapshot_from_core_findings(
        conn,
        scene_paths=["text/ch1.md"],
        findings_by_scene={"text/ch1.md": [
            _make_core_finding(lens="prose", evidence="prose finding"),
            _make_core_finding(lens="pacing", evidence="pacing finding"),
        ]},
        depth_mode="quick",
        created_at="2026-04-13T10:00:00",
        apply_silence=True,
    )
    states = {f.lens: f.state for f in snap.findings}
    assert states["prose"] == "silenced"
    assert states["pacing"] == "active"
