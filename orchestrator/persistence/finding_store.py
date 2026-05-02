"""Platform-owned finding store."""

import json
import sqlite3
from pathlib import Path
from typing import Optional

from orchestrator.persistence.path_utils import to_absolute, to_relative


class FindingStore:
    """CRUD operations for findings within a session."""

    @staticmethod
    def save_all(conn: sqlite3.Connection, session_id: int,
                 findings: list[dict], project_path: Path | None = None) -> None:
        """Insert all findings for a session (bulk insert after analysis).

        Each dict should match the Finding.to_dict(include_state=True) shape.
        """
        rows = []
        for f in findings:
            rows.append((
                session_id,
                f.get("number", 0),
                f.get("severity", "minor"),
                f.get("lens", "unknown"),
                f.get("location", ""),
                f.get("line_start"),
                f.get("line_end"),
                to_relative(project_path, f.get("scene_path")),
                f.get("evidence", ""),
                f.get("impact", ""),
                json.dumps(f.get("options", [])),
                json.dumps(f.get("flagged_by", [])),
                f.get("ambiguity_type"),
                int(f.get("stale", False)),
                f.get("status", "pending"),
                json.dumps(f.get("discussion_turns", [])),
                f.get("origin", "legacy"),
            ))

        conn.executemany(
            """INSERT INTO finding
               (session_id, number, severity, lens, location,
                line_start, line_end, scene_path, evidence, impact, options,
                flagged_by, ambiguity_type, stale, status,
                discussion_turns, origin)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()

    @staticmethod
    def load_all(conn: sqlite3.Connection, session_id: int, project_path: Path | None = None) -> list[dict]:
        """Load all findings for a session, ordered by number."""
        rows = conn.execute(
            "SELECT * FROM finding WHERE session_id = ? ORDER BY number",
            (session_id,),
        ).fetchall()
        return [FindingStore._row_to_dict(r, project_path=project_path) for r in rows]

    @staticmethod
    def get(conn: sqlite3.Connection, session_id: int,
            number: int, project_path: Path | None = None) -> Optional[dict]:
        """Load a single finding by session and number."""
        row = conn.execute(
            "SELECT * FROM finding WHERE session_id = ? AND number = ?",
            (session_id, number),
        ).fetchone()
        if row is None:
            return None
        return FindingStore._row_to_dict(row, project_path=project_path)

    @staticmethod
    def update(conn: sqlite3.Connection, session_id: int, number: int,
               **fields) -> None:
        """Update specific fields of a finding."""
        if not fields:
            return

        json_fields = {"options", "flagged_by", "discussion_turns"}
        set_clauses = []
        values = []
        for key, value in fields.items():
            set_clauses.append(f"{key} = ?")
            if key in json_fields:
                values.append(json.dumps(value))
            elif key == "stale":
                values.append(int(value))
            else:
                values.append(value)

        values.extend([session_id, number])
        sql = f"UPDATE finding SET {', '.join(set_clauses)} WHERE session_id = ? AND number = ?"
        conn.execute(sql, values)
        conn.commit()

    @staticmethod
    def update_by_id(conn: sqlite3.Connection, finding_id: int,
                     **fields) -> None:
        """Update specific fields of a finding by its primary key."""
        if not fields:
            return

        json_fields = {"options", "flagged_by", "discussion_turns"}
        set_clauses = []
        values = []
        for key, value in fields.items():
            set_clauses.append(f"{key} = ?")
            if key in json_fields:
                values.append(json.dumps(value))
            elif key == "stale":
                values.append(int(value))
            else:
                values.append(value)

        values.append(finding_id)
        sql = f"UPDATE finding SET {', '.join(set_clauses)} WHERE id = ?"
        conn.execute(sql, values)
        conn.commit()

    @staticmethod
    def remap_scene_paths(conn: sqlite3.Connection, session_id: int,
                          remap: dict[str, str],
                          project_path: Path | None = None) -> None:
        """Rewrite finding.scene_path values for a session using an old->new map."""
        if not remap:
            return

        updated = False
        for old_path, new_path in remap.items():
            if not old_path or not new_path or old_path == new_path:
                continue
            stored_old = to_relative(project_path, old_path)
            stored_new = to_relative(project_path, new_path)
            conn.execute(
                """UPDATE finding
                   SET scene_path = ?
                   WHERE session_id = ? AND scene_path = ?""",
                (stored_new, session_id, stored_old),
            )
            updated = True

        if updated:
            conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, project_path: Path | None = None) -> dict:
        """Convert a finding row to a plain dict, deserialising JSON columns."""
        d = dict(row)
        for key in ("options", "flagged_by", "discussion_turns"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    d[key] = []
        if "stale" in d:
            d["stale"] = bool(d["stale"])
        if project_path is not None and d.get("scene_path"):
            abs_path = to_absolute(project_path, d["scene_path"])
            if abs_path is not None:
                d["scene_path"] = str(abs_path)
        return d


__all__ = ["FindingStore"]
