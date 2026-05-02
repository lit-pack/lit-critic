"""Scene rename workflow for filesystem + projection/extraction/session references."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from orchestrator.services.scene_projection_service import discover_scene_relative_paths

_META_START = "@@META"
_META_END = "@@END"
_NULLISH_REFS = {"", "none", "null", "tbd", "n/a", "na"}


def rename_scene(
    project_path: Path,
    old_filename: str,
    new_filename: str,
    conn: sqlite3.Connection,
) -> dict:
    """Rename a scene file and update scene references in files + DB tables."""
    project_root = Path(project_path)
    old_file, old_key = _resolve_scene_file(project_root, old_filename)
    new_file, new_key = _resolve_scene_file(project_root, new_filename)

    if not old_file.exists():
        raise FileNotFoundError(f"Scene file not found: {old_file}")
    if new_file.exists():
        raise FileExistsError(f"Target scene file already exists: {new_file}")

    new_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.rename(new_file)

    mappings = _build_reference_mappings(project_root, old_file, new_file, old_key, new_key)
    updated_scene_files = _update_prev_next_references(project_root, mappings)

    updated_scene_projection_row = conn.execute(
        "UPDATE scene_projection SET scene_path = ? WHERE scene_path = ?",
        (new_key, old_key),
    ).rowcount
    updated_extracted_scene_metadata_row = conn.execute(
        "UPDATE extracted_scene_metadata SET scene_filename = ? WHERE scene_filename = ?",
        (new_key, old_key),
    ).rowcount
    updated_extracted_thread_events_rows = conn.execute(
        "UPDATE extracted_thread_events SET scene_filename = ? WHERE scene_filename = ?",
        (new_key, old_key),
    ).rowcount
    updated_extracted_timeline_row = conn.execute(
        "UPDATE extracted_timeline SET scene_filename = ? WHERE scene_filename = ?",
        (new_key, old_key),
    ).rowcount
    updated_character_source_rows = conn.execute(
        "UPDATE extracted_character_sources SET scene_filename = ? WHERE scene_filename = ?",
        (new_key, old_key),
    ).rowcount
    updated_term_source_rows = conn.execute(
        "UPDATE extracted_term_sources SET scene_filename = ? WHERE scene_filename = ?",
        (new_key, old_key),
    ).rowcount
    updated_character_first_seen_rows = conn.execute(
        "UPDATE extracted_characters SET first_seen = ? WHERE first_seen = ?",
        (new_key, old_key),
    ).rowcount
    updated_term_first_seen_rows = conn.execute(
        "UPDATE extracted_terms SET first_seen = ? WHERE first_seen = ?",
        (new_key, old_key),
    ).rowcount
    updated_thread_opened_rows = conn.execute(
        "UPDATE extracted_threads SET opened_in = ? WHERE opened_in = ?",
        (new_key, old_key),
    ).rowcount
    updated_thread_last_advanced_rows = conn.execute(
        "UPDATE extracted_threads SET last_advanced = ? WHERE last_advanced = ?",
        (new_key, old_key),
    ).rowcount
    updated_thread_resolved_rows = conn.execute(
        "UPDATE extracted_threads SET resolved_in = ? WHERE resolved_in = ?",
        (new_key, old_key),
    ).rowcount

    updated_projection_meta_rows = _update_projection_meta_refs(conn, mappings)
    updated_session_rows = _update_session_scene_paths(conn, mappings)
    conn.commit()

    return {
        "old_scene": old_key,
        "new_scene": new_key,
        "updated_scene_files": sorted(updated_scene_files),
        "updated_scene_projection_row": updated_scene_projection_row,
        "updated_scene_projection_meta_rows": updated_projection_meta_rows,
        "updated_extracted_scene_metadata_row": updated_extracted_scene_metadata_row,
        "updated_extracted_thread_events_rows": updated_extracted_thread_events_rows,
        "updated_extracted_timeline_row": updated_extracted_timeline_row,
        "updated_character_source_rows": updated_character_source_rows,
        "updated_term_source_rows": updated_term_source_rows,
        "updated_character_first_seen_rows": updated_character_first_seen_rows,
        "updated_term_first_seen_rows": updated_term_first_seen_rows,
        "updated_thread_opened_rows": updated_thread_opened_rows,
        "updated_thread_last_advanced_rows": updated_thread_last_advanced_rows,
        "updated_thread_resolved_rows": updated_thread_resolved_rows,
        "updated_session_rows": updated_session_rows,
    }


def _resolve_scene_file(project_root: Path, scene_filename: str) -> tuple[Path, str]:
    """Resolve a scene path and return (absolute_path, project-relative key)."""
    candidate = Path(scene_filename)
    if candidate.is_absolute():
        scene_file = candidate
        try:
            scene_key = candidate.relative_to(project_root).as_posix()
        except ValueError:
            scene_key = candidate.as_posix()
        return scene_file, scene_key

    scene_key = candidate.as_posix()
    return project_root / candidate, scene_key


def _build_reference_mappings(
    project_root: Path,
    old_file: Path,
    new_file: Path,
    old_key: str,
    new_key: str,
) -> list[tuple[str, str]]:
    """Build normalized old→new mappings used across files and DB references."""
    old_basename = old_file.name
    new_basename = new_file.name
    old_abs = old_file.resolve().as_posix()
    new_abs = new_file.resolve().as_posix()

    mappings = [(old_key, new_key), (old_abs, new_abs)]
    if old_basename != old_key:
        mappings.append((old_basename, new_basename))
    elif old_basename == old_key:
        mappings.append((old_basename, new_basename))

    # Ensure stable precedence (more specific before shorter aliases).
    mappings.sort(key=lambda pair: len(pair[0]), reverse=True)
    return mappings


def _update_prev_next_references(project_root: Path, mappings: list[tuple[str, str]]) -> list[str]:
    """Rewrite Prev/Next references across discoverable scene files."""
    updated_scene_files: list[str] = []
    for scene_key in discover_scene_relative_paths(project_root):
        scene_file = project_root / scene_key
        if not scene_file.exists():
            continue

        original = scene_file.read_text(encoding="utf-8")
        rewritten, changed = _rewrite_prev_next_refs(original, mappings)
        if not changed:
            continue

        scene_file.write_text(rewritten, encoding="utf-8")
        updated_scene_files.append(scene_key)

    return updated_scene_files


def _rewrite_prev_next_refs(scene_content: str, mappings: list[tuple[str, str]]) -> tuple[str, bool]:
    """Rewrite Prev/Next values inside the first @@META block."""
    lines = scene_content.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.strip() == _META_START), None)
    if start is None:
        return scene_content, False

    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start + 1) if line.strip() == _META_END),
        None,
    )
    if end is None:
        return scene_content, False

    changed = False
    for idx in range(start + 1, end):
        raw_line = lines[idx]
        stripped_line = raw_line.rstrip("\r\n")
        newline = raw_line[len(stripped_line) :]

        if ":" not in stripped_line:
            continue
        key_part, value_part = stripped_line.split(":", 1)
        key_terminal = key_part.strip().lower().split(".")[-1]
        if key_terminal not in {"prev", "next"}:
            continue

        value = value_part.strip()
        replacement = _replace_reference(value, mappings)
        if replacement is None:
            continue

        leading_ws_len = len(value_part) - len(value_part.lstrip())
        leading_ws = value_part[:leading_ws_len]
        lines[idx] = f"{key_part}:{leading_ws}{replacement}{newline}"
        changed = True

    if not changed:
        return scene_content, False
    return "".join(lines), True


def _update_projection_meta_refs(conn: sqlite3.Connection, mappings: list[tuple[str, str]]) -> int:
    """Rewrite Prev/Next references stored in scene_projection.meta_json payloads."""
    rows = conn.execute("SELECT scene_path, meta_json FROM scene_projection").fetchall()
    updated = 0
    for row in rows:
        raw_meta = row["meta_json"]
        if isinstance(raw_meta, str):
            try:
                meta = json.loads(raw_meta)
            except json.JSONDecodeError:
                continue
        elif isinstance(raw_meta, dict):
            meta = dict(raw_meta)
        else:
            continue

        if not isinstance(meta, dict):
            continue

        changed = False
        for key, value in list(meta.items()):
            if key.strip().lower().split(".")[-1] not in {"prev", "next"}:
                continue
            if not isinstance(value, str):
                continue
            replacement = _replace_reference(value, mappings)
            if replacement is None:
                continue
            meta[key] = replacement
            changed = True

        if not changed:
            continue

        conn.execute(
            "UPDATE scene_projection SET meta_json = ? WHERE scene_path = ?",
            (json.dumps(meta), row["scene_path"]),
        )
        updated += 1

    return updated


def _update_session_scene_paths(conn: sqlite3.Connection, mappings: list[tuple[str, str]]) -> int:
    """Update serialized session scene_path payloads for renamed scenes.

    The session table was dropped in v22. This function is a no-op on v22+
    databases and returns 0 gracefully.
    """
    try:
        rows = conn.execute("SELECT id, scene_path FROM session").fetchall()
    except sqlite3.OperationalError:
        return 0
    updated = 0
    for row in rows:
        raw_scene_path = row["scene_path"]
        scene_paths, was_json_list = _decode_session_scene_paths(raw_scene_path)

        changed = False
        rewritten_paths: list[str] = []
        for path in scene_paths:
            replacement = _replace_reference(path, mappings)
            if replacement is None:
                rewritten_paths.append(path)
                continue
            rewritten_paths.append(replacement)
            changed = True

        if not changed:
            continue

        if was_json_list:
            stored_value = json.dumps(rewritten_paths)
        else:
            stored_value = rewritten_paths[0] if rewritten_paths else ""

        conn.execute(
            "UPDATE session SET scene_path = ? WHERE id = ?",
            (stored_value, row["id"]),
        )
        updated += 1

    return updated


def _decode_session_scene_paths(raw_scene_path: str | None) -> tuple[list[str], bool]:
    """Decode legacy-or-json scene path storage; return (paths, is_json_list)."""
    if not raw_scene_path:
        return [], False
    try:
        parsed = json.loads(raw_scene_path)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item], True
    except (json.JSONDecodeError, TypeError):
        pass
    return [str(raw_scene_path)], False


def _replace_reference(value: str, mappings: list[tuple[str, str]]) -> str | None:
    """Return updated reference value when it matches any normalized mapping."""
    normalized_value = _normalize_ref(value)
    if normalized_value is None:
        return None

    for old_norm, new_norm in mappings:
        if normalized_value == old_norm:
            return new_norm
    return None


def _normalize_ref(value: str) -> str | None:
    """Normalize scene references for comparison, skipping nullish values."""
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.lower() in _NULLISH_REFS:
        return None
    return Path(stripped).as_posix()


def purge_orphaned_scene_refs(project_path: Path, conn: sqlite3.Connection) -> dict:
    """Delete DB rows whose scene path no longer matches any discoverable scene file.

    Scans all scene-filename-keyed tables and removes rows that reference scene
    files which are no longer present on disk (e.g. after an out-of-band rename
    or deletion).  Returns a dict with per-table deleted row counts.
    """
    project_root = Path(project_path)
    current_paths = set(discover_scene_relative_paths(project_root))

    def _purge_table(table: str, key_col: str) -> int:
        rows = conn.execute(f"SELECT {key_col} FROM {table}").fetchall()  # noqa: S608
        orphaned = [row[key_col] for row in rows if row[key_col] not in current_paths]
        deleted = 0
        for orphan in orphaned:
            deleted += conn.execute(
                f"DELETE FROM {table} WHERE {key_col} = ?",  # noqa: S608
                (orphan,),
            ).rowcount
        return deleted

    result = {
        "scene_projection": _purge_table("scene_projection", "scene_path"),
        "extracted_scene_metadata": _purge_table("extracted_scene_metadata", "scene_filename"),
        "extracted_character_sources": _purge_table("extracted_character_sources", "scene_filename"),
        "extracted_term_sources": _purge_table("extracted_term_sources", "scene_filename"),
        "extracted_thread_events": _purge_table("extracted_thread_events", "scene_filename"),
        "extracted_timeline": _purge_table("extracted_timeline", "scene_filename"),
    }
    conn.commit()
    return result


__all__ = ["purge_orphaned_scene_refs", "rename_scene"]
