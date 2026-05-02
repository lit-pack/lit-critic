"""Scene projection refresh and query utilities."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path

from orchestrator.facade import PlatformFacade
from orchestrator.persistence import SceneProjectionStore
from orchestrator.persistence.database import get_passive_connection
from orchestrator.user_config import get_user_config_path

_DEFAULT_SCENE_EXTENSIONS = ("txt",)
_DEFAULT_SCENE_FOLDER = "text"

logger = logging.getLogger(__name__)


def parse_scene_meta(scene_content: str) -> dict[str, str]:
    """Extract only ``prev``/``next`` fields from a scene's ``@@META`` block."""
    lines = scene_content.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "@@META"), None)
    if start is None:
        return {}

    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start + 1) if line.strip() == "@@END"),
        None,
    )
    if end is None:
        return {}

    meta: dict[str, str] = {}
    for raw_line in lines[start + 1 : end]:
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        normalized_key = key.strip().lower()
        if normalized_key not in {"prev", "next"}:
            continue
        meta[normalized_key] = value.strip()
    return meta


def compute_file_hash(path: Path) -> str:
    """Compute a stable short hash for file-level change detection."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:16]


def refresh_scene_projection(
    project_path: Path,
    scene_path: Path | str,
    conn: sqlite3.Connection,
) -> dict:
    """Refresh one scene projection record if source content changed."""
    project_root = Path(project_path)
    candidate = Path(scene_path)

    if candidate.is_absolute():
        scene_file = candidate
        try:
            stored_path = candidate.relative_to(project_root).as_posix()
        except ValueError:
            stored_path = candidate.as_posix()
    else:
        scene_file = project_root / candidate
        stored_path = candidate.as_posix()

    file_hash = compute_file_hash(scene_file)
    if not SceneProjectionStore.is_stale(conn, stored_path, file_hash, project_path=project_root):
        return {"scene_path": stored_path, "updated": False, "file_hash": file_hash}

    scene_content = PlatformFacade.load_scene_text(scene_file)
    meta = parse_scene_meta(scene_content)
    SceneProjectionStore.upsert(
        conn,
        scene_path=stored_path,
        scene_id=None,
        file_hash=file_hash,
        meta_json=meta,
        project_path=project_root,
    )
    return {"scene_path": stored_path, "updated": True, "file_hash": file_hash}


def refresh_all_scenes(project_path: Path, conn: sqlite3.Connection) -> list[dict]:
    """Refresh projections for all discovered scene files under configured roots."""
    project_root = Path(project_path)
    scene_files = _discover_scene_files(project_root)
    if not scene_files:
        return []

    refresh_results: list[dict] = []
    for scene_file in scene_files:
        rel_path = scene_file.relative_to(project_root)
        refresh_results.append(refresh_scene_projection(project_root, rel_path, conn))
    return refresh_results


def list_scene_projections(project_path: Path) -> list[dict]:
    """Return stored scene projections filtered to currently discoverable scene paths."""
    project_root = Path(project_path)
    discoverable_paths = set(discover_scene_relative_paths(project_root))

    conn = get_passive_connection(project_root)
    if conn is None:
        return []
    try:
        rows = SceneProjectionStore.load_all(conn)
        if not discoverable_paths:
            return []

        filtered: list[dict] = []
        for row in rows:
            raw_path = str(row.get("scene_path") or "")
            candidate = Path(raw_path)
            if candidate.is_absolute():
                try:
                    normalized = candidate.relative_to(project_root).as_posix()
                except ValueError:
                    normalized = candidate.as_posix()
            else:
                normalized = candidate.as_posix()

            if normalized in discoverable_paths:
                filtered.append(row)
        return filtered
    finally:
        conn.close()


def discover_scene_relative_paths(project_path: Path) -> list[str]:
    """Discover scene files with fallback-to-project-root when needed."""
    project_root = Path(project_path)
    return [path.relative_to(project_root).as_posix() for path in _discover_scene_files(project_root)]


def _discover_scene_files(project_root: Path) -> list[Path]:
    """Discover candidate scene files from configured root, then project root fallback."""
    scene_folder, scene_extensions = _load_scene_discovery_settings()
    search_root = project_root / scene_folder
    allowed_suffixes = {f".{ext.lower().lstrip('.')}" for ext in scene_extensions if ext}

    if not allowed_suffixes:
        return []

    def _collect(root: Path) -> list[Path]:
        return sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in allowed_suffixes
            ),
            key=lambda path: path.relative_to(project_root).as_posix(),
        )

    normalized_folder = scene_folder.strip().replace("\\", "/")

    if search_root.exists():
        if normalized_folder in {".", ""}:
            default_root = project_root / _DEFAULT_SCENE_FOLDER
            if default_root.exists():
                default_scene_files = _collect(default_root)
                if default_scene_files:
                    return default_scene_files

            return _collect(search_root)

        return _collect(search_root)

    logger.warning(
        "Configured scene_folder %r does not exist under %s — scene discovery returning empty list. "
        "Check your scene_folder setting in user config.",
        scene_folder,
        project_root,
    )
    return []


def _load_scene_discovery_settings() -> tuple[str, tuple[str, ...]]:
    """Load scene discovery settings from user config with sensible defaults."""
    scene_folder = _DEFAULT_SCENE_FOLDER
    scene_extensions = _DEFAULT_SCENE_EXTENSIONS

    config_path = get_user_config_path()
    if not config_path.exists():
        return scene_folder, scene_extensions

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return scene_folder, scene_extensions

    if isinstance(payload, dict):
        raw_folder = payload.get("scene_folder")
        if isinstance(raw_folder, str) and raw_folder.strip():
            scene_folder = raw_folder.strip()

        raw_extensions = payload.get("scene_extensions")
        if isinstance(raw_extensions, list):
            normalized = [
                ext.strip().lower().lstrip(".")
                for ext in raw_extensions
                if isinstance(ext, str) and ext.strip()
            ]
            if normalized:
                scene_extensions = tuple(normalized)

    return scene_folder, scene_extensions


__all__ = [
    "compute_file_hash",
    "discover_scene_relative_paths",
    "list_scene_projections",
    "parse_scene_meta",
    "refresh_all_scenes",
    "refresh_scene_projection",
]