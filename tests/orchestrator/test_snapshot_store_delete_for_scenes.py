"""Unit tests for SnapshotStore.delete_for_scenes (Task 4).

Verifies that delete_for_scenes removes snapshots and findings for the
specified scenes without touching snapshots for other scenes.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from orchestrator.persistence.snapshot_store import SnapshotStore


def _insert_snapshot(conn: sqlite3.Connection, scene_path: str, source_hash: str) -> int:
    """Insert a minimal snapshot row and one finding row. Returns snapshot id."""
    cur = conn.execute(
        """INSERT INTO analysis_snapshot
           (scene_paths, depth_mode, source_file_hash, created_at)
           VALUES (?, 'quick', ?, datetime('now'))""",
        (json.dumps([scene_path]), source_hash),
    )
    snap_id = cur.lastrowid
    conn.execute(
        """INSERT INTO snapshot_finding
           (snapshot_id, number, severity, lens, location, scene_path,
            evidence, impact, options, flagged_by, state)
           VALUES (?, 1, 'minor', 'prose', 'p1', ?, 'ev', 'imp', '[]', '[]', 'active')""",
        (snap_id, scene_path),
    )
    conn.commit()
    return snap_id


class TestDeleteForScenes:
    def test_deletes_matching_snapshot_and_findings(self, db_conn: sqlite3.Connection) -> None:
        """delete_for_scenes removes the snapshot and its findings for the given scene."""
        snap_id = _insert_snapshot(db_conn, "text/chapter01.txt", "hash_a")

        deleted = SnapshotStore.delete_for_scenes(db_conn, ["text/chapter01.txt"])
        db_conn.commit()

        assert deleted == 1
        row = db_conn.execute(
            "SELECT id FROM analysis_snapshot WHERE id = ?", (snap_id,)
        ).fetchone()
        assert row is None, "Snapshot should have been deleted"
        findings = db_conn.execute(
            "SELECT id FROM snapshot_finding WHERE snapshot_id = ?", (snap_id,)
        ).fetchall()
        assert findings == [], "Findings should have been deleted"

    def test_does_not_delete_other_scenes_snapshot(self, db_conn: sqlite3.Connection) -> None:
        """delete_for_scenes leaves snapshots for other scenes untouched."""
        snap_a = _insert_snapshot(db_conn, "text/chapter01.txt", "hash_a")
        snap_b = _insert_snapshot(db_conn, "text/chapter02.txt", "hash_b")

        deleted = SnapshotStore.delete_for_scenes(db_conn, ["text/chapter01.txt"])
        db_conn.commit()

        assert deleted == 1
        # snap_a is gone
        assert db_conn.execute(
            "SELECT id FROM analysis_snapshot WHERE id = ?", (snap_a,)
        ).fetchone() is None
        # snap_b is untouched
        assert db_conn.execute(
            "SELECT id FROM analysis_snapshot WHERE id = ?", (snap_b,)
        ).fetchone() is not None

    def test_no_matching_scene_returns_zero(self, db_conn: sqlite3.Connection) -> None:
        """delete_for_scenes returns 0 when no snapshots match — no error."""
        count = SnapshotStore.delete_for_scenes(db_conn, ["text/nonexistent.txt"])
        db_conn.commit()
        assert count == 0

    def test_empty_scene_list_returns_zero(self, db_conn: sqlite3.Connection) -> None:
        """delete_for_scenes returns 0 for an empty scene list — no error."""
        _insert_snapshot(db_conn, "text/chapter01.txt", "hash_a")
        count = SnapshotStore.delete_for_scenes(db_conn, [])
        db_conn.commit()
        assert count == 0
