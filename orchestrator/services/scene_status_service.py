"""Scene status service — single source of truth for scene freshness.

Exports a computed ``SceneStatus`` for every scene in the project.
Status is derived on every call from the filesystem and DB tables;
nothing is persisted.  See ``specs/loop-redesign-architecture.md`` §3.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.path_utils import to_relative
from orchestrator.services.scene_projection_service import (
    compute_file_hash,
    discover_scene_relative_paths,
)

logger = logging.getLogger(__name__)

# Default backoff for failed extractions: 10 minutes.
FAILURE_BACKOFF_SECONDS = 600


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class SceneStatus(Enum):
    """Four mutually exclusive scene lifecycle statuses.

    Analysis is manual-only; ``analysis_due`` has been removed.
    """

    extraction_due = "extraction_due"
    extracted = "extracted"
    analyzed = "analyzed"
    failed = "failed"


@dataclass(frozen=True)
class SceneStatusRecord:
    """Snapshot of a single scene's computed status."""

    scene_key: str
    status: SceneStatus
    locked: bool
    current_hash: str | None  # None if file missing on disk
    last_extracted_hash: str | None
    last_analyzed_hash: str | None
    failed_at: str | None  # ISO timestamp, set when status == failed


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def list_scene_statuses(
    project_root: Path,
    conn: sqlite3.Connection,
) -> list[SceneStatusRecord]:
    """Return computed status for every discoverable scene in the project.

    This is the primary public entry point.  It batch-loads DB state to
    avoid N+1 queries, then derives status per scene.
    """
    scene_keys = discover_scene_relative_paths(project_root)
    if not scene_keys:
        return []

    # Bulk-load extraction metadata keyed by scene filename.
    esm_by_filename: dict[str, dict] = {
        row["scene_filename"]: row
        for row in ExtractionStore.load_all_scene_metadata(conn)
    }

    # Bulk-load latest snapshot source_file_hash keyed by relative scene path.
    snap_hashes = _bulk_latest_snapshot_hashes(conn, scene_keys, project_root)

    results: list[SceneStatusRecord] = []
    for scene_key in scene_keys:
        record = _compute_scene_status(
            scene_key,
            project_root=project_root,
            esm_by_filename=esm_by_filename,
            snap_hash_by_scene=snap_hashes,
        )
        results.append(record)
    return results


def list_analyzable_scenes(
    project_root: Path,
    conn: sqlite3.Connection,
) -> list[dict]:
    """Return scenes that are ready to be analyzed.

    A scene is analyzable when its status is ``extraction_due`` (file changed,
    analysis will see new content) or ``extracted`` (extraction is fresh but no
    up-to-date analysis snapshot exists).

    Returns a list of dicts with keys ``scene_key``, ``path`` (absolute), and
    ``status`` (string value of :class:`SceneStatus`).
    """
    analyzable_statuses = {SceneStatus.extraction_due, SceneStatus.extracted}
    records = list_scene_statuses(project_root, conn)
    return [
        {
            "scene_key": r.scene_key,
            "path": str(project_root / r.scene_key),
            "status": r.status.value,
        }
        for r in records
        if r.status in analyzable_statuses
    ]


def describe_status_reason(record: SceneStatusRecord) -> str:
    """Human-readable one-liner explaining *why* a scene has its current status.

    Used by the loop's INFO-level decision logging (architecture §7).
    """
    if record.current_hash is None:
        return f"{record.scene_key}: file missing on disk"

    match record.status:
        case SceneStatus.extraction_due:
            if record.last_extracted_hash is None:
                return f"{record.scene_key}: never extracted"
            return (
                f"{record.scene_key}: file edited since last extraction"
                f" (current={record.current_hash},"
                f" extracted={record.last_extracted_hash})"
            )
        case SceneStatus.extracted:
            return (
                f"{record.scene_key}: extraction fresh, no analysis snapshot yet"
            )
        case SceneStatus.analyzed:
            return f"{record.scene_key}: up to date"
        case SceneStatus.failed:
            return (
                f"{record.scene_key}: failed at {record.failed_at}, in backoff"
            )
    return f"{record.scene_key}: unknown status {record.status}"  # pragma: no cover


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_scene_status(
    scene_key: str,
    *,
    project_root: Path,
    esm_by_filename: dict[str, dict],
    snap_hash_by_scene: dict[str, str],
) -> SceneStatusRecord:
    """Derive the status of a single scene from filesystem + pre-loaded DB state.

    Implements the derivation rule from architecture §3.2.
    """
    scene_file = project_root / scene_key

    # --- current file hash (None when file is missing on disk) ---
    try:
        current_hash: str | None = compute_file_hash(scene_file)
    except (OSError, FileNotFoundError):
        current_hash = None

    # --- extraction metadata ---
    # extraction_service persists rows keyed by the scene's relative path
    # (e.g. "text/chapter01.md"), so look up by scene_key, not basename.
    esm = esm_by_filename.get(scene_key)
    locked = bool(esm and int(esm.get("extraction_locked") or 0) == 1)
    last_extracted_hash = esm.get("content_hash") if esm else None

    # --- latest snapshot hash for this scene ---
    last_analyzed_hash: str | None = snap_hash_by_scene.get(scene_key)

    # --- derivation (architecture §3.2) ---

    if current_hash is None:
        # File missing on disk — report extraction_due so the loop attempts
        # extraction (which will fail), keeping the status honest.
        return SceneStatusRecord(
            scene_key=scene_key,
            status=SceneStatus.extraction_due,
            locked=locked,
            current_hash=None,
            last_extracted_hash=last_extracted_hash,
            last_analyzed_hash=last_analyzed_hash,
            failed_at=None,
        )

    if esm is None or esm.get("content_hash") != current_hash:
        # Never extracted, or file edited since last extraction.
        return SceneStatusRecord(
            scene_key=scene_key,
            status=SceneStatus.extraction_due,
            locked=locked,
            current_hash=current_hash,
            last_extracted_hash=last_extracted_hash,
            last_analyzed_hash=last_analyzed_hash,
            failed_at=None,
        )

    if esm.get("extract_status") == "failed":
        failed_at = esm.get("extracted_at")
        if not _failure_backoff_elapsed(failed_at):
            # Within backoff window — stay in failed status.
            return SceneStatusRecord(
                scene_key=scene_key,
                status=SceneStatus.failed,
                locked=locked,
                current_hash=current_hash,
                last_extracted_hash=last_extracted_hash,
                last_analyzed_hash=last_analyzed_hash,
                failed_at=failed_at,
            )
        # Backoff elapsed — eligible for retry.
        return SceneStatusRecord(
            scene_key=scene_key,
            status=SceneStatus.extraction_due,
            locked=locked,
            current_hash=current_hash,
            last_extracted_hash=last_extracted_hash,
            last_analyzed_hash=last_analyzed_hash,
            failed_at=failed_at,
        )

    # Extraction is fresh — check analysis freshness via snapshot.
    if last_analyzed_hash is None or last_analyzed_hash != current_hash:
        # No snapshot or stale snapshot — scene is extracted, waiting for
        # the user to trigger manual analysis.
        return SceneStatusRecord(
            scene_key=scene_key,
            status=SceneStatus.extracted,
            locked=locked,
            current_hash=current_hash,
            last_extracted_hash=last_extracted_hash,
            last_analyzed_hash=last_analyzed_hash,
            failed_at=None,
        )

    return SceneStatusRecord(
        scene_key=scene_key,
        status=SceneStatus.analyzed,
        locked=locked,
        current_hash=current_hash,
        last_extracted_hash=last_extracted_hash,
        last_analyzed_hash=last_analyzed_hash,
        failed_at=None,
    )


def _bulk_latest_snapshot_hashes(
    conn: sqlite3.Connection,
    scene_keys: list[str],
    project_root: Path,
) -> dict[str, str]:
    """Return ``{scene_key: source_file_hash}`` for the latest snapshot per scene.

    Loads all snapshot headers (no findings) in a single query, then
    indexes by scene path.  First match per scene wins because rows are
    ordered by ``created_at DESC``.
    """
    rows = conn.execute(
        "SELECT scene_paths, source_file_hash "
        "FROM analysis_snapshot ORDER BY created_at DESC"
    ).fetchall()

    wanted = set(scene_keys)
    result: dict[str, str] = {}

    for row in rows:
        raw_paths = row["scene_paths"] if isinstance(row, sqlite3.Row) else row[0]
        if not raw_paths:
            continue
        try:
            paths: list[str] = json.loads(raw_paths) if isinstance(raw_paths, str) else raw_paths
        except (json.JSONDecodeError, TypeError):
            continue

        source_hash = (
            row["source_file_hash"] if isinstance(row, sqlite3.Row) else row[1]
        ) or ""
        for sp in paths:
            rel = to_relative(project_root, sp)
            if rel in wanted and rel not in result:
                result[rel] = source_hash

    return result


def _failure_backoff_elapsed(failed_at: str | None) -> bool:
    """Return True if enough time has passed since the failure for a retry."""
    if not failed_at:
        return True
    try:
        failed_dt = datetime.fromisoformat(failed_at)
        if failed_dt.tzinfo is None:
            failed_dt = failed_dt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - failed_dt).total_seconds()
        return elapsed >= FAILURE_BACKOFF_SECONDS
    except (ValueError, TypeError):
        return True


__all__ = [
    "SceneStatus",
    "SceneStatusRecord",
    "describe_status_reason",
    "list_analyzable_scenes",
    "list_scene_statuses",
]
