"""CRUD operations for knowledge entity state persistence tables.

Tables:
- ``knowledge_review_flags``  — one row per flagged entity
- ``knowledge_staleness_cache`` — one row per stale entity; sentinel row
  ``(category='__all__', entity_key='__all__')`` represents all-stale condition.
"""

import sqlite3
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeStateStore:
    """Static CRUD methods for knowledge_review_flags and knowledge_staleness_cache."""

    # ------------------------------------------------------------------
    # Review flags
    # ------------------------------------------------------------------

    @staticmethod
    def save_review_flags(conn: sqlite3.Connection, flags: list[dict]) -> None:
        """Upsert a list of review flag dicts.

        Each dict must contain ``category`` and ``entity_key``.
        Optional keys: ``reason`` (default ``''``), ``flagged_at`` (default now).
        """
        now = _now_iso()
        conn.executemany(
            """INSERT OR REPLACE INTO knowledge_review_flags
               (category, entity_key, reason, flagged_at)
               VALUES (:category, :entity_key, :reason, :flagged_at)""",
            [
                {
                    "category": f["category"],
                    "entity_key": f["entity_key"],
                    "reason": f.get("reason", ""),
                    "flagged_at": f.get("flagged_at", now),
                }
                for f in flags
            ],
        )
        conn.commit()

    @staticmethod
    def load_review_flags(conn: sqlite3.Connection) -> list[dict]:
        """Return all review flag rows as plain dicts.

        Returns an empty list gracefully if the table does not yet exist (e.g.
        when called via a passive connection against a pre-v16 database that has
        not been migrated yet).
        """
        try:
            rows = conn.execute(
                "SELECT category, entity_key, reason, flagged_at FROM knowledge_review_flags"
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    @staticmethod
    def delete_review_flag(conn: sqlite3.Connection, category: str, entity_key: str) -> None:
        """Delete a single review flag by (category, entity_key)."""
        conn.execute(
            "DELETE FROM knowledge_review_flags WHERE category = ? AND entity_key = ?",
            (category, entity_key),
        )
        conn.commit()

    @staticmethod
    def clear_review_flags(conn: sqlite3.Connection) -> None:
        """Delete all review flags."""
        conn.execute("DELETE FROM knowledge_review_flags")
        conn.commit()

    # ------------------------------------------------------------------
    # Staleness cache
    # ------------------------------------------------------------------

    @staticmethod
    def save_staleness_cache(
        conn: sqlite3.Connection,
        stale_entities: list[dict],
        all_stale: bool = False,
    ) -> None:
        """Replace the staleness cache with the provided entity list.

        If ``all_stale`` is True, inserts only the sentinel row
        ``(category='__all__', entity_key='__all__')`` which signals that
        every entity is considered stale.  Otherwise, inserts one row per
        entry in *stale_entities*.

        Each dict must contain ``category`` and ``entity_key``.
        Optional key: ``source_path`` (default ``''``).

        This method always clears the existing cache first (replace, not append).
        """
        now = _now_iso()
        conn.execute("DELETE FROM knowledge_staleness_cache")

        if all_stale:
            conn.execute(
                """INSERT INTO knowledge_staleness_cache
                   (category, entity_key, source_path, cached_at)
                   VALUES ('__all__', '__all__', '', ?)""",
                (now,),
            )
        else:
            conn.executemany(
                """INSERT OR REPLACE INTO knowledge_staleness_cache
                   (category, entity_key, source_path, cached_at)
                   VALUES (:category, :entity_key, :source_path, :cached_at)""",
                [
                    {
                        "category": e["category"],
                        "entity_key": e["entity_key"],
                        "source_path": e.get("source_path", ""),
                        "cached_at": e.get("cached_at", now),
                    }
                    for e in stale_entities
                ],
            )
        conn.commit()

    @staticmethod
    def load_staleness_cache(conn: sqlite3.Connection) -> dict:
        """Return the staleness cache as ``{"all_stale": bool, "entities": list[dict]}``.

        If the sentinel row is present, ``all_stale`` is True and ``entities``
        is empty.  Otherwise, ``all_stale`` is False and ``entities`` contains
        all non-sentinel rows.

        Returns the empty default gracefully if the table does not yet exist
        (passive connection against a pre-v17 database).
        """
        try:
            rows = conn.execute(
                "SELECT category, entity_key, source_path, cached_at FROM knowledge_staleness_cache"
            ).fetchall()
        except sqlite3.OperationalError:
            return {"all_stale": False, "entities": []}

        for row in rows:
            if row["category"] == "__all__" and row["entity_key"] == "__all__":
                return {"all_stale": True, "entities": []}

        return {"all_stale": False, "entities": [dict(r) for r in rows]}

    @staticmethod
    def clear_staleness_cache(conn: sqlite3.Connection) -> None:
        """Delete all staleness cache rows (including the sentinel if present)."""
        conn.execute("DELETE FROM knowledge_staleness_cache")
        conn.commit()

    @staticmethod
    def delete_staleness_entry(
        conn: sqlite3.Connection, category: str, entity_key: str
    ) -> None:
        """Remove a single entity's staleness row.  Does not affect the sentinel."""
        conn.execute(
            "DELETE FROM knowledge_staleness_cache WHERE category = ? AND entity_key = ?",
            (category, entity_key),
        )
        conn.commit()


__all__ = ["KnowledgeStateStore"]
