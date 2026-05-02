"""Index projection refresh and query utilities."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from orchestrator.persistence import IndexProjectionStore
from orchestrator.persistence.database import get_connection, get_passive_connection
from orchestrator.services.audit_service import _split_h3_entries
from orchestrator.services.scene_projection_service import compute_file_hash

# Author-maintained index files that exist on disk.
# CAST.md, GLOSSARY.md, THREADS.md, and TIMELINE.md have been removed;
# knowledge from those files is now stored in SQLite.
_INDEX_FILENAMES = (
    "CANON.md",
    "STYLE.md",
)

_INDEX_SCOPE_BY_NAME = {
    "CANON.md": "canon",
    "STYLE.md": "style",
}


def parse_index_entries(index_name: str, content: str) -> list[dict] | None:
    """Parse structured index entries from a markdown index file content.

    ``index_name`` is the dict key (e.g. ``"cast"`` or ``"CANON.md"``), not
    necessarily the filesystem filename.
    """
    if index_name == "STYLE.md":
        return None
    if not content.strip():
        return []

    lines = content.splitlines()
    section_by_line = _sections_by_line(lines)
    scope = _INDEX_SCOPE_BY_NAME.get(index_name, Path(index_name).stem.lower())

    entries: list[dict] = []
    for heading, line_no, _entry_text in _split_h3_entries(content):
        entry = heading.split("<!--", 1)[0].strip()
        if not entry:
            continue
        entries.append(
            {
                "scope": scope,
                "entry": entry,
                "source_file": Path(index_name).name,
                "source_section": section_by_line.get(line_no, ""),
                "source_line": line_no,
            }
        )
    return entries


def _notify_projection_refreshed(index_name: str) -> None:
    """Push a ``projection_refreshed`` SSE event through the background loop.

    Called after any successful projection upsert so the extension re-queries
    staleness regardless of which code path triggered the write (loop cycle,
    knowledge refresh, or explicit API call). No-op when the loop isn't
    initialised (unit tests, CLI-only flows).
    """
    try:
        # Local import to avoid a circular import at module load time.
        from core.loop import get_loop

        loop = get_loop()
        if loop is None or not hasattr(loop, "_emit"):
            return
        loop._emit({
            "event": "projection_refreshed",
            "updated": 1,
            "indexes": [index_name],
        })
    except Exception:
        # Never let notification failures block the projection write.
        pass


def refresh_index_projection(
    project_path: Path,
    index_name: str | Path,
    conn: sqlite3.Connection,
) -> dict:
    """Refresh one index projection if the source hash changed."""
    project_root = Path(project_path)
    candidate = Path(index_name)

    if candidate.is_absolute():
        index_file = candidate
        stored_name = candidate.name
    else:
        index_file = project_root / candidate
        stored_name = candidate.as_posix()

    if not index_file.exists():
        return {"index_name": stored_name, "updated": False, "missing": True}

    raw_content_hash = compute_file_hash(index_file)
    if not IndexProjectionStore.is_stale(conn, stored_name, raw_content_hash):
        return {
            "index_name": stored_name,
            "updated": False,
            "file_hash": raw_content_hash,
        }

    content = index_file.read_text(encoding="utf-8")
    entries = parse_index_entries(stored_name, content)
    IndexProjectionStore.upsert(
        conn,
        index_name=stored_name,
        file_hash=raw_content_hash,
        entries_json=entries,
        raw_content_hash=raw_content_hash,
    )
    _notify_projection_refreshed(stored_name)
    return {
        "index_name": stored_name,
        "updated": True,
        "file_hash": raw_content_hash,
    }



def refresh_all_indexes(project_path: Path, conn: sqlite3.Connection) -> list[dict]:
    """Refresh all discovered canonical index files for a project."""
    project_root = Path(project_path)
    refresh_results: list[dict] = []

    for filename in _INDEX_FILENAMES:
        index_file = project_root / filename
        if not index_file.exists():
            continue
        refresh_results.append(refresh_index_projection(project_root, filename, conn))
    return refresh_results


def list_index_projections(project_path: Path) -> list[dict]:
    """Return all stored index projections for a project."""
    conn = get_passive_connection(Path(project_path))
    if conn is None:
        return []
    try:
        return IndexProjectionStore.load_all(conn)
    finally:
        conn.close()


def get_stale_indexes(project_path: Path) -> list[str]:
    """Return index keys that are missing, new, or hash-mismatched."""
    project_root = Path(project_path)
    conn = get_connection(project_root)
    try:
        stored = {row["index_name"] for row in IndexProjectionStore.load_all(conn)}
        existing = {
            filename
            for filename in _INDEX_FILENAMES
            if (project_root / filename).exists()
        }
        candidates = sorted(stored | existing)

        stale: list[str] = []
        for key in candidates:
            index_file = project_root / key
            if not index_file.exists():
                stale.append(key)
                continue
            current_hash = compute_file_hash(index_file)
            if IndexProjectionStore.is_stale(conn, key, current_hash):
                stale.append(key)
        return stale
    finally:
        conn.close()


def _sections_by_line(lines: list[str]) -> dict[int, str]:
    """Map heading line numbers to nearest preceding section title."""
    section_starts: list[tuple[int, str]] = []
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            section_starts.append((line_no, stripped[3:].strip()))

    line_to_section: dict[int, str] = {}
    current_section = ""
    section_idx = 0
    for line_no, line in enumerate(lines, start=1):
        while section_idx < len(section_starts) and section_starts[section_idx][0] <= line_no:
            current_section = section_starts[section_idx][1]
            section_idx += 1
        if line.strip().startswith("### "):
            line_to_section[line_no] = current_section
    return line_to_section


__all__ = [
    "get_stale_indexes",
    "list_index_projections",
    "parse_index_entries",
    "refresh_all_indexes",
    "refresh_index_projection",
]
