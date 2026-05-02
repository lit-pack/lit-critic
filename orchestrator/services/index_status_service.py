"""Index status service — single source of truth for index file freshness.

Exports a computed ``IndexStatus`` for every canonical index file
(CANON.md, STYLE.md) in the project.  Status is derived on every call
from the filesystem and ``index_projection`` DB table; nothing is
persisted.  See ``specs/loop-redesign-architecture.md`` §4.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from orchestrator.persistence.index_projection_store import IndexProjectionStore
from orchestrator.services.scene_projection_service import compute_file_hash

logger = logging.getLogger(__name__)

# Canonical index files the platform tracks.
_INDEX_FILENAMES = (
    "CANON.md",
    "STYLE.md",
)

# CANON changes affect extracted knowledge (characters, terms, threads);
# STYLE does not — it influences analysis tone but not knowledge entities.
_AFFECTS_KNOWLEDGE: dict[str, bool] = {
    "CANON.md": True,
    "STYLE.md": False,
}


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class IndexStatus(Enum):
    """Three mutually exclusive index lifecycle statuses."""

    current = "current"
    stale = "stale"
    absent = "absent"


@dataclass(frozen=True)
class IndexStatusRecord:
    """Snapshot of a single index file's computed status."""

    index_name: str
    status: IndexStatus
    affects_knowledge: bool
    current_hash: str | None  # None if file missing on disk
    stored_hash: str | None  # None if no projection row exists


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def list_index_statuses(
    project_root: Path,
    conn: sqlite3.Connection,
) -> list[IndexStatusRecord]:
    """Return computed status for every canonical index file.

    This is the primary public entry point.  It batch-loads stored
    projection hashes once, then derives status per index.
    """
    stored_hashes = _load_stored_hashes(conn)

    results: list[IndexStatusRecord] = []
    for index_name in _INDEX_FILENAMES:
        record = _compute_index_status(
            index_name,
            project_root=project_root,
            stored_hashes=stored_hashes,
        )
        results.append(record)
    return results


def get_index_status(
    name: str,
    *,
    project_root: Path,
    conn: sqlite3.Connection,
) -> IndexStatusRecord:
    """Return computed status for a single index file by name."""
    stored_hashes = _load_stored_hashes(conn)
    return _compute_index_status(
        name,
        project_root=project_root,
        stored_hashes=stored_hashes,
    )


def describe_status_reason(record: IndexStatusRecord) -> str:
    """Human-readable one-liner explaining *why* an index has its current status.

    Used by the loop's INFO-level decision logging (architecture §7).
    """
    match record.status:
        case IndexStatus.current:
            return f"{record.index_name}: up to date"
        case IndexStatus.stale:
            if record.stored_hash is None:
                return f"{record.index_name}: never projected"
            return (
                f"{record.index_name}: file edited since last projection"
                f" (current={record.current_hash},"
                f" stored={record.stored_hash})"
            )
        case IndexStatus.absent:
            return f"{record.index_name}: file does not exist on disk"
    return f"{record.index_name}: unknown status {record.status}"  # pragma: no cover


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_index_status(
    index_name: str,
    *,
    project_root: Path,
    stored_hashes: dict[str, str],
) -> IndexStatusRecord:
    """Derive the status of a single index from filesystem + pre-loaded DB state."""
    affects_knowledge = _AFFECTS_KNOWLEDGE.get(index_name, False)
    stored_hash = stored_hashes.get(index_name)

    index_file = project_root / index_name

    # --- current file hash (None when file is missing on disk) ---
    if not index_file.exists():
        return IndexStatusRecord(
            index_name=index_name,
            status=IndexStatus.absent,
            affects_knowledge=affects_knowledge,
            current_hash=None,
            stored_hash=stored_hash,
        )

    current_hash = compute_file_hash(index_file)

    if stored_hash is None or stored_hash != current_hash:
        return IndexStatusRecord(
            index_name=index_name,
            status=IndexStatus.stale,
            affects_knowledge=affects_knowledge,
            current_hash=current_hash,
            stored_hash=stored_hash,
        )

    return IndexStatusRecord(
        index_name=index_name,
        status=IndexStatus.current,
        affects_knowledge=affects_knowledge,
        current_hash=current_hash,
        stored_hash=stored_hash,
    )


def _load_stored_hashes(conn: sqlite3.Connection) -> dict[str, str]:
    """Load stored index projection hashes keyed by canonical file name.

    Normalises ``index_name`` to just the filename component so callers
    can look up by e.g. ``"CANON.md"`` regardless of stored path format.
    """
    result: dict[str, str] = {}
    for row in IndexProjectionStore.load_all(conn):
        canonical = Path(row["index_name"]).name
        result[canonical] = row["file_hash"]
    return result


__all__ = [
    "IndexStatus",
    "IndexStatusRecord",
    "describe_status_reason",
    "get_index_status",
    "list_index_statuses",
]
