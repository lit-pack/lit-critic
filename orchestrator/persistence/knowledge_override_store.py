"""Platform-owned overrides for extracted knowledge."""

from __future__ import annotations

import sqlite3
from datetime import datetime


class KnowledgeOverrideStore:
    """CRUD operations and override application helpers."""

    @staticmethod
    def upsert_override(
        conn: sqlite3.Connection,
        category: str,
        entity_key: str,
        field_name: str,
        value: str,
    ) -> None:
        """Insert or update an author override for an extracted field."""
        now = datetime.now().isoformat()
        conn.execute(
            """INSERT INTO knowledge_overrides (
                   category,
                   entity_key,
                   field_name,
                   override_value,
                   created_at
               ) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(category, entity_key, field_name) DO UPDATE SET
                   override_value = excluded.override_value,
                   created_at = excluded.created_at""",
            (category, entity_key, field_name, value, now),
        )
        conn.commit()

    @staticmethod
    def delete_override(
        conn: sqlite3.Connection,
        category: str,
        entity_key: str,
        field_name: str,
    ) -> bool:
        """Delete an override and return True when one existed."""
        cursor = conn.execute(
            """DELETE FROM knowledge_overrides
               WHERE category = ? AND entity_key = ? AND field_name = ?""",
            (category, entity_key, field_name),
        )
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def delete_all_overrides_for_entity(
        conn: sqlite3.Connection,
        category: str,
        entity_key: str,
    ) -> int:
        """Delete all overrides for an entity. Returns the number of rows deleted."""
        cursor = conn.execute(
            """DELETE FROM knowledge_overrides
               WHERE category = ? AND entity_key = ?""",
            (category, entity_key),
        )
        conn.commit()
        return cursor.rowcount

    @staticmethod
    def load_overrides_for_entity(
        conn: sqlite3.Connection,
        category: str,
        entity_key: str,
    ) -> list[dict]:
        """Load overrides for a specific entity key in one category."""
        rows = conn.execute(
            """SELECT *
               FROM knowledge_overrides
               WHERE category = ? AND entity_key = ?
               ORDER BY field_name""",
            (category, entity_key),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def load_all_overrides(
        conn: sqlite3.Connection,
        category: str | None = None,
    ) -> list[dict]:
        """Load all overrides, optionally filtered by category."""
        if category is None:
            rows = conn.execute(
                """SELECT *
                   FROM knowledge_overrides
                   ORDER BY category, entity_key, field_name"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT *
                   FROM knowledge_overrides
                   WHERE category = ?
                   ORDER BY entity_key, field_name""",
                (category,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def apply_overrides(
        conn: sqlite3.Connection,
        category: str,
        raw_entities: list[dict],
        entity_key_field: str,
    ) -> list[dict]:
        """Apply stored overrides onto raw extraction entities."""
        override_rows = KnowledgeOverrideStore.load_all_overrides(conn, category)
        by_entity: dict[str, dict[str, str]] = {}
        for row in override_rows:
            by_entity.setdefault(row["entity_key"], {})[row["field_name"]] = row[
                "override_value"
            ]

        merged: list[dict] = []
        for entity in raw_entities:
            updated = dict(entity)
            entity_key = str(updated.get(entity_key_field, ""))
            for field_name, override_value in by_entity.get(entity_key, {}).items():
                updated[field_name] = override_value
            merged.append(updated)
        return merged


__all__ = ["KnowledgeOverrideStore"]
