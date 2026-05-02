"""Platform-owned scene projection store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from orchestrator.persistence.path_utils import to_absolute, to_relative


class SceneProjectionStore:
    """CRUD-style operations for scene projection records."""

    @staticmethod
    def upsert(
        conn: sqlite3.Connection,
        scene_path: str,
        scene_id: str | None,
        file_hash: str,
        meta_json: str | dict,
        project_path: Path | None = None,
    ) -> None:
        """Insert or update a projected scene row."""
        now = datetime.now().isoformat()
        serialized_meta = (
            meta_json if isinstance(meta_json, str) else json.dumps(meta_json)
        )
        stored_path = to_relative(project_path, scene_path)
        conn.execute(
            """INSERT INTO scene_projection
               (scene_path, scene_id, file_hash, meta_json, last_refreshed_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(scene_path) DO UPDATE SET
                   scene_id = excluded.scene_id,
                   file_hash = excluded.file_hash,
                   meta_json = excluded.meta_json,
                   last_refreshed_at = excluded.last_refreshed_at""",
            (stored_path, scene_id, file_hash, serialized_meta, now),
        )
        conn.commit()

    @staticmethod
    def load_all(conn: sqlite3.Connection, project_path: Path | None = None) -> list[dict]:
        """Load all scene projection rows ordered by scene path."""
        rows = conn.execute(
            "SELECT * FROM scene_projection ORDER BY scene_path"
        ).fetchall()
        return [SceneProjectionStore._row_to_dict(row, project_path=project_path) for row in rows]

    @staticmethod
    def load_by_path(conn: sqlite3.Connection, scene_path: str, project_path: Path | None = None) -> dict | None:
        """Load a single scene projection row by scene path."""
        lookup = to_relative(project_path, scene_path)
        row = conn.execute(
            "SELECT * FROM scene_projection WHERE scene_path = ?",
            (lookup,),
        ).fetchone()
        if row is None:
            return None
        return SceneProjectionStore._row_to_dict(row, project_path=project_path)

    @staticmethod
    def delete_by_path(conn: sqlite3.Connection, scene_path: str, project_path: Path | None = None) -> None:
        """Delete a projected scene row by scene path."""
        lookup = to_relative(project_path, scene_path)
        conn.execute(
            "DELETE FROM scene_projection WHERE scene_path = ?",
            (lookup,),
        )
        conn.commit()

    @staticmethod
    def is_stale(
        conn: sqlite3.Connection,
        scene_path: str,
        current_hash: str,
        project_path: Path | None = None,
    ) -> bool:
        """Return True if the stored row is missing or hash-mismatched."""
        lookup = to_relative(project_path, scene_path)
        row = conn.execute(
            "SELECT file_hash FROM scene_projection WHERE scene_path = ?",
            (lookup,),
        ).fetchone()
        if row is None:
            return True
        return row[0] != current_hash

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, project_path: Path | None = None) -> dict:
        """Convert a row to dict with parsed ``meta_json`` and absolutized ``scene_path``."""
        data = dict(row)
        raw_meta = data.get("meta_json")
        if isinstance(raw_meta, str):
            try:
                data["meta_json"] = json.loads(raw_meta)
            except (json.JSONDecodeError, TypeError):
                pass
        if project_path is not None and data.get("scene_path"):
            abs_path = to_absolute(project_path, data["scene_path"])
            if abs_path is not None:
                data["scene_path"] = str(abs_path)
        return data


__all__ = ["SceneProjectionStore"]
