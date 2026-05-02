"""Platform-owned index projection store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime


class IndexProjectionStore:
    """CRUD-style operations for index projection records."""

    @staticmethod
    def upsert(
        conn: sqlite3.Connection,
        index_name: str,
        file_hash: str,
        entries_json: str | list[dict] | None,
        raw_content_hash: str | None = None,
    ) -> None:
        """Insert or update a projected index row."""
        now = datetime.now().isoformat()
        resolved_raw_content_hash = raw_content_hash or file_hash
        serialized_entries: str | None
        if entries_json is None or isinstance(entries_json, str):
            serialized_entries = entries_json
        else:
            serialized_entries = json.dumps(entries_json)

        conn.execute(
            """INSERT INTO index_projection
               (index_name, file_hash, entries_json, raw_content_hash, last_refreshed_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(index_name) DO UPDATE SET
                   file_hash = excluded.file_hash,
                   entries_json = excluded.entries_json,
                   raw_content_hash = excluded.raw_content_hash,
                   last_refreshed_at = excluded.last_refreshed_at""",
            (
                index_name,
                file_hash,
                serialized_entries,
                resolved_raw_content_hash,
                now,
            ),
        )
        conn.commit()

    @staticmethod
    def load_all(conn: sqlite3.Connection) -> list[dict]:
        """Load all index projection rows ordered by index name."""
        rows = conn.execute(
            "SELECT * FROM index_projection ORDER BY index_name"
        ).fetchall()
        return [IndexProjectionStore._row_to_dict(row) for row in rows]

    @staticmethod
    def load_by_name(conn: sqlite3.Connection, index_name: str) -> dict | None:
        """Load a single index projection row by index file name."""
        row = conn.execute(
            "SELECT * FROM index_projection WHERE index_name = ?",
            (index_name,),
        ).fetchone()
        if row is None:
            return None
        return IndexProjectionStore._row_to_dict(row)

    @staticmethod
    def is_stale(
        conn: sqlite3.Connection,
        index_name: str,
        current_hash: str,
    ) -> bool:
        """Return True if the stored row is missing or hash-mismatched."""
        row = conn.execute(
            "SELECT file_hash FROM index_projection WHERE index_name = ?",
            (index_name,),
        ).fetchone()
        if row is None:
            return True
        return row[0] != current_hash

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert row to dict with parsed ``entries_json`` when possible."""
        data = dict(row)
        raw_entries = data.get("entries_json")
        if isinstance(raw_entries, str):
            try:
                data["entries_json"] = json.loads(raw_entries)
            except (json.JSONDecodeError, TypeError):
                pass
        return data


__all__ = ["IndexProjectionStore"]
