"""
Tests for Phase 2 of the loop-analysis-decoupling plan:
- Snapshot replacement on re-analysis (Task 5)
- Resolved-finding detection → learning resolution entries (Task 5)
- SnapshotStore.delete_for_scenes (Task 4)

These tests exercise the DB-level components of the cleanup logic inserted into
start_analysis() without invoking the full analysis pipeline (which requires LLM
calls). Each test uses the in-memory db_conn fixture from conftest.
"""
from __future__ import annotations

import pytest

from core.domain import AnalysisSnapshot, SnapshotFinding
from orchestrator.persistence.snapshot_store import SnapshotStore
from orchestrator.persistence.learning_store import LearningStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(scene_path: str, findings: list[SnapshotFinding] | None = None) -> AnalysisSnapshot:
    """Build a minimal AnalysisSnapshot for persistence."""
    return AnalysisSnapshot(
        scene_paths=[scene_path],
        depth_mode="deep",
        frontier_model="sonnet",
        checker_model="haiku",
        quick_model="haiku",
        scene_hashes={scene_path: "abc123"},
        source_file_hash="",
        index_context_hash="",
        created_at="2026-01-01T00:00:00",
        findings=findings or [],
    )


def _make_finding(lens: str, evidence: str, scene_path: str, state: str = "active") -> SnapshotFinding:
    """Build a minimal SnapshotFinding with a correlation_key."""
    return SnapshotFinding(
        number=1,
        severity="major",
        lens=lens,
        location="Line 5",
        line_start=5,
        line_end=6,
        scene_path=scene_path,
        evidence=evidence,
        impact="Impact",
        options=[],
        flagged_by=[lens],
        ambiguity_type=None,
        state=state,
        correlation_key=SnapshotFinding.build_correlation_key(scene_path, lens, 5, evidence),
    )


# ---------------------------------------------------------------------------
# (a) Snapshot replacement: after delete_for_scenes + create, only one snapshot exists
# ---------------------------------------------------------------------------

class TestSnapshotReplacement:
    """Verify that delete_for_scenes removes the old snapshot before the new one is saved."""

    def test_old_snapshot_deleted_when_new_analysis_runs(self, db_conn):
        """After delete_for_scenes + create, only one snapshot exists for the scene."""
        scene = "/project/scene01.md"

        # Create the first snapshot (from a previous analysis run)
        snap1 = _make_snapshot(scene)
        SnapshotStore.create(db_conn, snap1)
        db_conn.commit()

        assert snap1.id is not None
        prev = SnapshotStore.get_latest_for_scene(db_conn, scene)
        assert prev is not None

        # Simulate new analysis: delete old snapshots, then create new one
        deleted = SnapshotStore.delete_for_scenes(db_conn, [scene])
        db_conn.commit()

        snap2 = _make_snapshot(scene)
        SnapshotStore.create(db_conn, snap2)
        db_conn.commit()

        # Only one snapshot should remain — verify via get_latest and direct id lookup
        current = SnapshotStore.get_latest_for_scene(db_conn, scene)
        assert current is not None
        assert current.id == snap2.id
        # Old snapshot id must be gone
        old_row = db_conn.execute(
            "SELECT id FROM analysis_snapshot WHERE id = ?", (snap1.id,)
        ).fetchone()
        assert old_row is None

    def test_delete_for_scenes_removes_findings_too(self, db_conn):
        """Findings (snapshot_finding rows) are cascade-deleted with their snapshot."""
        scene = "/project/scene02.md"
        finding = _make_finding("prose", "Repetitive sentence starts", scene)
        snap = _make_snapshot(scene, findings=[finding])
        SnapshotStore.create(db_conn, snap)
        db_conn.commit()

        assert snap.id is not None
        finding_count = db_conn.execute(
            "SELECT COUNT(*) FROM snapshot_finding WHERE snapshot_id = ?", (snap.id,)
        ).fetchone()[0]
        assert finding_count == 1

        SnapshotStore.delete_for_scenes(db_conn, [scene])
        db_conn.commit()

        # Findings should be gone too (cascade)
        finding_count_after = db_conn.execute(
            "SELECT COUNT(*) FROM snapshot_finding WHERE snapshot_id = ?", (snap.id,)
        ).fetchone()[0]
        assert finding_count_after == 0

    def test_delete_for_scenes_does_not_affect_other_scenes(self, db_conn):
        """Snapshot for a different scene must be untouched by delete_for_scenes."""
        scene_a = "/project/sceneA.md"
        scene_b = "/project/sceneB.md"

        snap_a = _make_snapshot(scene_a)
        snap_b = _make_snapshot(scene_b)
        SnapshotStore.create(db_conn, snap_a)
        SnapshotStore.create(db_conn, snap_b)
        db_conn.commit()

        SnapshotStore.delete_for_scenes(db_conn, [scene_a])
        db_conn.commit()

        # scene_a's snapshot gone, scene_b's snapshot untouched
        assert SnapshotStore.get_latest_for_scene(db_conn, scene_a) is None
        assert SnapshotStore.get_latest_for_scene(db_conn, scene_b) is not None


# ---------------------------------------------------------------------------
# (b) Resolved-finding detection generates a learning resolution entry
# ---------------------------------------------------------------------------

class TestResolvedFindingLearning:
    """Verify that disappeared findings produce resolution learning entries."""

    def test_resolved_finding_creates_learning_entry(self, db_conn):
        """A finding in the previous snapshot absent from the new analysis → resolution entry."""
        scene = "/project/scene03.md"
        old_finding = _make_finding("prose", "Repetitive sentence starts", scene)
        snap = _make_snapshot(scene, findings=[old_finding])
        SnapshotStore.create(db_conn, snap)
        db_conn.commit()

        # Simulate: new analysis returns NO findings for this scene
        prev_snap = SnapshotStore.get_latest_for_scene(db_conn, scene)
        assert prev_snap is not None
        prev_findings = prev_snap.findings

        # Build new correlation key set (empty — no new findings)
        new_corr_keys: set[str] = set()

        resolved = [
            pf for pf in prev_findings
            if pf.state != "resolved" and pf.correlation_key not in new_corr_keys
        ]
        assert len(resolved) == 1

        # Persist resolution learning entry
        for rf in resolved:
            desc = "Resolved: " + ((rf.evidence or "")[:80] or rf.lens or "unknown")
            LearningStore.add_resolution(db_conn, desc)
        db_conn.commit()

        # Verify the learning entry exists
        data = LearningStore.load(db_conn)
        resolutions = data.get("resolutions", [])
        assert len(resolutions) == 1
        assert "Repetitive sentence starts" in resolutions[0]["description"]

    def test_already_resolved_finding_is_not_double_counted(self, db_conn):
        """Findings already in state=resolved are skipped by the detection logic."""
        scene = "/project/scene04.md"
        already_resolved = _make_finding("structure", "Missing goal", scene, state="resolved")
        snap = _make_snapshot(scene, findings=[already_resolved])
        SnapshotStore.create(db_conn, snap)
        db_conn.commit()

        prev_snap = SnapshotStore.get_latest_for_scene(db_conn, scene)
        prev_findings = prev_snap.findings

        new_corr_keys: set[str] = set()
        resolved = [
            pf for pf in prev_findings
            if pf.state != "resolved" and pf.correlation_key not in new_corr_keys
        ]
        # Already-resolved finding must not appear again
        assert len(resolved) == 0

    def test_still_present_finding_is_not_resolved(self, db_conn):
        """A finding that reappears in the new analysis is NOT marked resolved."""
        scene = "/project/scene05.md"
        finding = _make_finding("clarity", "Unclear pronoun", scene)
        snap = _make_snapshot(scene, findings=[finding])
        SnapshotStore.create(db_conn, snap)
        db_conn.commit()

        prev_snap = SnapshotStore.get_latest_for_scene(db_conn, scene)
        prev_findings = prev_snap.findings

        # New analysis also has the same finding (same correlation key)
        new_corr_keys = {finding.correlation_key}
        resolved = [
            pf for pf in prev_findings
            if pf.state != "resolved" and pf.correlation_key not in new_corr_keys
        ]
        assert len(resolved) == 0


# ---------------------------------------------------------------------------
# (c) No previous snapshot — start_analysis succeeds without crashing
# ---------------------------------------------------------------------------

class TestNoPreviousSnapshot:
    """Verify graceful handling when no prior snapshot exists."""

    def test_get_latest_returns_none_for_fresh_scene(self, db_conn):
        """A scene with no snapshot history returns None from get_latest_for_scene."""
        scene = "/project/brand-new-scene.md"
        result = SnapshotStore.get_latest_for_scene(db_conn, scene)
        assert result is None

    def test_delete_for_scenes_with_no_prior_snapshots_returns_zero(self, db_conn):
        """delete_for_scenes on a scene with no snapshots returns 0 without error."""
        deleted = SnapshotStore.delete_for_scenes(db_conn, ["/project/nonexistent.md"])
        assert deleted == 0

    def test_cleanup_flow_handles_no_previous_snapshot_gracefully(self, db_conn):
        """The full cleanup flow (load → detect → delete → create) works with no prior snapshot."""
        scene = "/project/first-run.md"

        # 1. Load previous — returns empty
        prev_snap = SnapshotStore.get_latest_for_scene(db_conn, scene)
        assert prev_snap is None
        prev_findings = prev_snap.findings if prev_snap else []
        assert prev_findings == []

        # 2. No resolved findings to process
        resolved = [
            pf for pf in prev_findings
            if pf.state != "resolved"
        ]
        assert resolved == []

        # 3. Delete returns 0 — no error
        deleted = SnapshotStore.delete_for_scenes(db_conn, [scene])
        assert deleted == 0

        # 4. Create new snapshot succeeds
        snap = _make_snapshot(scene)
        SnapshotStore.create(db_conn, snap)
        db_conn.commit()

        assert snap.id is not None
        assert SnapshotStore.get_latest_for_scene(db_conn, scene) is not None


# ---------------------------------------------------------------------------
# (d) SnapshotStore.delete_for_scenes edge cases
# ---------------------------------------------------------------------------

class TestDeleteForScenes:
    """Direct tests for SnapshotStore.delete_for_scenes."""

    def test_delete_for_scenes_empty_list_returns_zero(self, db_conn):
        """Passing an empty list returns 0 and makes no changes."""
        deleted = SnapshotStore.delete_for_scenes(db_conn, [])
        assert deleted == 0

    def test_delete_for_scenes_nonexistent_path_returns_zero(self, db_conn):
        """Passing a scene path that has no snapshots returns 0 without error."""
        deleted = SnapshotStore.delete_for_scenes(db_conn, ["/no/such/scene.md"])
        assert deleted == 0

    def test_delete_for_scenes_returns_correct_count(self, db_conn):
        """Returns the number of snapshot rows actually deleted."""
        scene = "/project/countme.md"
        snap1 = _make_snapshot(scene)
        snap2 = _make_snapshot(scene)
        SnapshotStore.create(db_conn, snap1)
        SnapshotStore.create(db_conn, snap2)
        db_conn.commit()

        deleted = SnapshotStore.delete_for_scenes(db_conn, [scene])
        db_conn.commit()
        assert deleted == 2

    def test_delete_for_scenes_multi_scene_removes_all_matched(self, db_conn):
        """When multiple scene paths are passed, all matching snapshots are removed."""
        scene_x = "/project/sceneX.md"
        scene_y = "/project/sceneY.md"
        scene_z = "/project/sceneZ.md"

        for scene in (scene_x, scene_y, scene_z):
            SnapshotStore.create(db_conn, _make_snapshot(scene))
        db_conn.commit()

        deleted = SnapshotStore.delete_for_scenes(db_conn, [scene_x, scene_y])
        db_conn.commit()

        assert deleted == 2
        assert SnapshotStore.get_latest_for_scene(db_conn, scene_x) is None
        assert SnapshotStore.get_latest_for_scene(db_conn, scene_y) is None
        assert SnapshotStore.get_latest_for_scene(db_conn, scene_z) is not None
