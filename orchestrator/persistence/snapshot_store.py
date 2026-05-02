"""Persistence layer for AnalysisSnapshot and SnapshotFinding (read-only model)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from core.domain import AnalysisSnapshot, SnapshotFinding
from orchestrator.persistence.path_utils import to_absolute, to_relative


class SnapshotStore:
    """CRUD operations for ``analysis_snapshot`` and ``snapshot_finding`` tables."""

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @staticmethod
    def create(
        conn: sqlite3.Connection,
        snapshot: AnalysisSnapshot,
        project_path: Path | None = None,
    ) -> int:
        """Persist a new snapshot (with all its findings) and return the row id.

        The ``snapshot.id`` and each ``finding.id`` / ``finding.snapshot_id``
        are updated in-place on the passed objects.
        """
        cur = conn.execute(
            """INSERT INTO analysis_snapshot
               (scene_paths, depth_mode, frontier_model, checker_model,
                quick_model, scene_hashes, source_file_hash,
                index_context_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                json.dumps(snapshot.scene_paths),
                snapshot.depth_mode,
                snapshot.frontier_model,
                snapshot.checker_model,
                snapshot.quick_model,
                json.dumps(snapshot.scene_hashes),
                snapshot.source_file_hash,
                snapshot.index_context_hash,
                snapshot.created_at,
            ),
        )
        snapshot_id = cur.lastrowid
        snapshot.id = snapshot_id  # type: ignore[assignment]

        if snapshot.findings:
            rows = []
            for f in snapshot.findings:
                # Ensure correlation_key is set.
                if not f.correlation_key:
                    f.correlation_key = SnapshotFinding.build_correlation_key(
                        f.scene_path, f.lens, f.line_start, f.evidence
                    )
                rows.append((
                    snapshot_id,
                    f.number,
                    f.severity,
                    f.lens,
                    f.location,
                    f.line_start,
                    f.line_end,
                    to_relative(project_path, f.scene_path) if f.scene_path else "",
                    f.evidence,
                    f.impact,
                    json.dumps(f.options),
                    json.dumps(f.flagged_by),
                    f.ambiguity_type,
                    f.state,
                    f.correlation_key,
                ))

            conn.executemany(
                """INSERT INTO snapshot_finding
                   (snapshot_id, number, severity, lens, location,
                    line_start, line_end, scene_path, evidence, impact,
                    options, flagged_by, ambiguity_type, state, correlation_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

            # Back-fill DB ids into the finding objects.
            db_findings = conn.execute(
                "SELECT id, number FROM snapshot_finding WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchall()
            id_by_number = {r["number"]: r["id"] for r in db_findings}
            for f in snapshot.findings:
                f.id = id_by_number.get(f.number)
                f.snapshot_id = snapshot_id

        conn.commit()
        return snapshot_id  # type: ignore[return-value]

    @staticmethod
    def update_finding_state(
        conn: sqlite3.Connection,
        finding_id: int,
        state: str,
    ) -> None:
        """Update a single snapshot finding's state (active/silenced/resolved)."""
        conn.execute(
            "UPDATE snapshot_finding SET state = ? WHERE id = ?",
            (state, finding_id),
        )
        conn.commit()

    @staticmethod
    def delete_all(conn: sqlite3.Connection) -> int:
        """Delete all snapshots and their findings. Returns the number of snapshots deleted."""
        count = conn.execute("SELECT COUNT(*) FROM analysis_snapshot").fetchone()[0]
        conn.execute("DELETE FROM snapshot_finding")
        conn.execute("DELETE FROM analysis_snapshot")
        conn.commit()
        return count

    @staticmethod
    def delete_by_id(conn: sqlite3.Connection, snapshot_id: int) -> bool:
        """Delete a single snapshot and its findings. Returns True if a row was deleted."""
        conn.execute(
            "DELETE FROM snapshot_finding WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        cur = conn.execute(
            "DELETE FROM analysis_snapshot WHERE id = ?",
            (snapshot_id,),
        )
        conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def delete_for_scenes(
        conn: sqlite3.Connection,
        scene_paths: list[str],
        project_path: Path | None = None,
    ) -> int:
        """Delete all snapshots whose scene_paths JSON contains any of the given paths.

        Deletes both the ``analysis_snapshot`` rows and their cascaded
        ``snapshot_finding`` rows.  Returns the number of snapshot rows deleted.

        Must be called inside the caller's transaction — this method does NOT
        call ``conn.commit()``.
        """
        if not scene_paths:
            return 0

        # Collect matching snapshot IDs using LIKE-based JSON search (same
        # pattern as get_latest_for_scene).
        snapshot_ids: set[int] = set()
        for sp in scene_paths:
            rel_path = to_relative(project_path, sp) if project_path else sp
            pattern = f'%"{rel_path}"%'
            rows = conn.execute(
                "SELECT id FROM analysis_snapshot WHERE scene_paths LIKE ?",
                (pattern,),
            ).fetchall()
            for row in rows:
                snapshot_ids.add(row["id"] if isinstance(row, sqlite3.Row) else row[0])

        if not snapshot_ids:
            return 0

        placeholders = ",".join("?" * len(snapshot_ids))
        ids_list = list(snapshot_ids)
        conn.execute(
            f"DELETE FROM snapshot_finding WHERE snapshot_id IN ({placeholders})",
            ids_list,
        )
        cur = conn.execute(
            f"DELETE FROM analysis_snapshot WHERE id IN ({placeholders})",
            ids_list,
        )
        return cur.rowcount

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @staticmethod
    def get(
        conn: sqlite3.Connection,
        snapshot_id: int,
        project_path: Path | None = None,
    ) -> Optional[AnalysisSnapshot]:
        """Load a snapshot and all its findings."""
        row = conn.execute(
            "SELECT * FROM analysis_snapshot WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return None

        snapshot = SnapshotStore._row_to_snapshot(row)
        snapshot.findings = SnapshotStore._load_findings(
            conn, snapshot_id, project_path=project_path
        )
        return snapshot

    @staticmethod
    def get_latest_for_scene(
        conn: sqlite3.Connection,
        scene_path: str,
        project_path: Path | None = None,
    ) -> Optional[AnalysisSnapshot]:
        """Return the most recent snapshot that contains *scene_path*.

        The stored scene_paths column is a JSON list; we use a LIKE search on
        the JSON-encoded relative path for simplicity (SQLite has no native
        JSON_CONTAINS on older versions).
        """
        rel_path = to_relative(project_path, scene_path) if project_path else scene_path
        # Search for the relative path within the JSON array string.
        pattern = f'%"{rel_path}"%'
        row = conn.execute(
            """SELECT * FROM analysis_snapshot
               WHERE scene_paths LIKE ?
               ORDER BY created_at DESC
               LIMIT 1""",
            (pattern,),
        ).fetchone()
        if row is None:
            return None

        snapshot = SnapshotStore._row_to_snapshot(row)
        snapshot.findings = SnapshotStore._load_findings(
            conn, snapshot.id, project_path=project_path  # type: ignore[arg-type]
        )
        return snapshot

    @staticmethod
    def list_recent(
        conn: sqlite3.Connection,
        limit: int = 20,
    ) -> list[AnalysisSnapshot]:
        """Return the most recent snapshots (without findings) for listing."""
        rows = conn.execute(
            "SELECT * FROM analysis_snapshot ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [SnapshotStore._row_to_snapshot(r) for r in rows]

    @staticmethod
    def get_finding(
        conn: sqlite3.Connection,
        finding_id: int,
        project_path: Path | None = None,
    ) -> Optional[SnapshotFinding]:
        """Load a single snapshot finding by its DB id."""
        row = conn.execute(
            "SELECT * FROM snapshot_finding WHERE id = ?",
            (finding_id,),
        ).fetchone()
        if row is None:
            return None
        return SnapshotStore._row_to_finding(row, project_path=project_path)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> AnalysisSnapshot:
        d = dict(row)
        return AnalysisSnapshot(
            id=d["id"],
            scene_paths=_json_list(d.get("scene_paths")),
            depth_mode=d.get("depth_mode", "quick"),
            frontier_model=d.get("frontier_model", ""),
            checker_model=d.get("checker_model", ""),
            quick_model=d.get("quick_model", ""),
            scene_hashes=_json_dict(d.get("scene_hashes")),
            source_file_hash=d.get("source_file_hash", ""),
            index_context_hash=d.get("index_context_hash", ""),
            created_at=d.get("created_at", ""),
        )

    @staticmethod
    def _load_findings(
        conn: sqlite3.Connection,
        snapshot_id: int,
        project_path: Path | None = None,
    ) -> list[SnapshotFinding]:
        rows = conn.execute(
            "SELECT * FROM snapshot_finding WHERE snapshot_id = ? ORDER BY number",
            (snapshot_id,),
        ).fetchall()
        return [SnapshotStore._row_to_finding(r, project_path=project_path) for r in rows]

    @staticmethod
    def _row_to_finding(
        row: sqlite3.Row,
        project_path: Path | None = None,
    ) -> SnapshotFinding:
        d = dict(row)
        scene_path = d.get("scene_path", "") or ""
        if project_path and scene_path:
            abs_p = to_absolute(project_path, scene_path)
            if abs_p is not None:
                scene_path = str(abs_p)
        return SnapshotFinding(
            id=d["id"],
            snapshot_id=d.get("snapshot_id"),
            number=d.get("number", 0),
            severity=d.get("severity", "minor"),
            lens=d.get("lens", "unknown"),
            location=d.get("location", ""),
            line_start=d.get("line_start"),
            line_end=d.get("line_end"),
            scene_path=scene_path,
            evidence=d.get("evidence", ""),
            impact=d.get("impact", ""),
            options=_json_list(d.get("options")),
            flagged_by=_json_list(d.get("flagged_by")),
            ambiguity_type=d.get("ambiguity_type"),
            state=d.get("state", "active"),
            correlation_key=d.get("correlation_key", ""),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


__all__ = ["SnapshotStore"]
