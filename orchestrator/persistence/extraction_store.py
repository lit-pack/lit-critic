"""Platform-owned extracted knowledge store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone


class ExtractionStore:
    """CRUD-style operations for extracted knowledge records."""

    @staticmethod
    def upsert_scene_metadata(
        conn: sqlite3.Connection,
        scene_filename: str,
        content_hash: str,
        extracted_at: str | None = None,
        location: str | None = None,
        pov: str | None = None,
        tense: str | None = None,
        tense_notes: str | None = None,
        cast_present: str | list[str] | None = None,
        objective: str | None = None,
        cont_anchors: str | list[str] | dict | None = None,
        extract_status: str = "ok",
        extraction_locked: int = 0,
        locked_at: str | None = None,
    ) -> None:
        """Insert or update extracted scene metadata."""
        resolved_extracted_at = extracted_at or datetime.now(timezone.utc).isoformat()
        serialized_cast_present = ExtractionStore._serialize_json(cast_present)
        serialized_cont_anchors = ExtractionStore._serialize_json(cont_anchors)

        conn.execute(
            """INSERT INTO extracted_scene_metadata (
                   scene_filename,
                   content_hash,
                   extracted_at,
                   location,
                   pov,
                   tense,
                   tense_notes,
                   cast_present,
                   objective,
                   cont_anchors,
                   extract_status,
                   extraction_locked,
                   locked_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(scene_filename) DO UPDATE SET
                   content_hash = excluded.content_hash,
                   extracted_at = excluded.extracted_at,
                   location = excluded.location,
                   pov = excluded.pov,
                   tense = excluded.tense,
                   tense_notes = excluded.tense_notes,
                   cast_present = excluded.cast_present,
                   objective = excluded.objective,
                   cont_anchors = excluded.cont_anchors,
                   extract_status = excluded.extract_status,
                   extraction_locked = excluded.extraction_locked,
                   locked_at = excluded.locked_at""",
            (
                scene_filename,
                content_hash,
                resolved_extracted_at,
                location,
                pov,
                tense,
                tense_notes,
                serialized_cast_present,
                objective,
                serialized_cont_anchors,
                extract_status,
                extraction_locked,
                locked_at,
            ),
        )
        conn.commit()

    @staticmethod
    def load_scene_metadata(
        conn: sqlite3.Connection,
        scene_filename: str,
    ) -> dict | None:
        """Load extracted metadata for a single scene."""
        row = conn.execute(
            "SELECT * FROM extracted_scene_metadata WHERE scene_filename = ?",
            (scene_filename,),
        ).fetchone()
        if row is None:
            return None
        return ExtractionStore._row_to_dict(row)

    @staticmethod
    def load_all_scene_metadata(conn: sqlite3.Connection) -> list[dict]:
        """Load all extracted scene metadata rows ordered by scene filename."""
        rows = conn.execute(
            "SELECT * FROM extracted_scene_metadata ORDER BY scene_filename"
        ).fetchall()
        return [ExtractionStore._row_to_dict(row) for row in rows]

    @staticmethod
    def upsert_character(
        conn: sqlite3.Connection,
        name: str,
        aka: str | list[str] | None = None,
        category: str | None = None,
        traits: str | dict | None = None,
        relationships: str | list[dict] | None = None,
        first_seen: str | None = None,
        last_updated: str | None = None,
    ) -> None:
        """Insert or update a character extraction row."""
        resolved_last_updated = last_updated or datetime.now(timezone.utc).isoformat()
        serialized_aka = ExtractionStore._serialize_json(aka)
        serialized_traits = ExtractionStore._serialize_json(traits)
        serialized_relationships = ExtractionStore._serialize_json(relationships)

        conn.execute(
            """INSERT INTO extracted_characters (
                   name,
                   aka,
                   category,
                   traits,
                   relationships,
                   first_seen,
                   last_updated
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   aka = excluded.aka,
                   category = excluded.category,
                   traits = excluded.traits,
                   relationships = excluded.relationships,
                   first_seen = excluded.first_seen,
                   last_updated = excluded.last_updated""",
            (
                name,
                serialized_aka,
                category,
                serialized_traits,
                serialized_relationships,
                first_seen,
                resolved_last_updated,
            ),
        )
        conn.commit()

    @staticmethod
    def delete_character(conn: sqlite3.Connection, name: str) -> bool:
        """Delete a character extraction row. Returns True if a row was removed."""
        cursor = conn.execute(
            "DELETE FROM extracted_characters WHERE name = ?", (name,)
        )
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def load_all_characters(conn: sqlite3.Connection) -> list[dict]:
        """Load all extracted character rows ordered by canonical name."""
        rows = conn.execute(
            "SELECT * FROM extracted_characters ORDER BY name"
        ).fetchall()
        return [ExtractionStore._row_to_dict(row) for row in rows]

    @staticmethod
    def upsert_term(
        conn: sqlite3.Connection,
        term: str,
        category: str | None = None,
        definition: str | None = None,
        translation: str | None = None,
        notes: str | None = None,
        first_seen: str | None = None,
        last_updated: str | None = None,
    ) -> None:
        """Insert or update a term extraction row."""
        resolved_last_updated = last_updated or datetime.now(timezone.utc).isoformat()

        conn.execute(
            """INSERT INTO extracted_terms (
                   term,
                   category,
                   definition,
                   translation,
                   notes,
                   first_seen,
                   last_updated
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(term) DO UPDATE SET
                   category = excluded.category,
                   definition = excluded.definition,
                   translation = excluded.translation,
                   notes = excluded.notes,
                   first_seen = excluded.first_seen,
                   last_updated = excluded.last_updated""",
            (
                term,
                category,
                definition,
                translation,
                notes,
                first_seen,
                resolved_last_updated,
            ),
        )
        conn.commit()

    @staticmethod
    def delete_term(conn: sqlite3.Connection, term: str) -> bool:
        """Delete a term extraction row. Returns True if a row was removed."""
        cursor = conn.execute(
            "DELETE FROM extracted_terms WHERE term = ?", (term,)
        )
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def load_all_terms(conn: sqlite3.Connection) -> list[dict]:
        """Load all extracted term rows ordered by term."""
        rows = conn.execute("SELECT * FROM extracted_terms ORDER BY term").fetchall()
        return [ExtractionStore._row_to_dict(row) for row in rows]

    @staticmethod
    def upsert_character_source(
        conn: sqlite3.Connection,
        name: str,
        scene_filename: str,
    ) -> None:
        """Record that character *name* was sourced from *scene_filename*."""
        conn.execute(
            """INSERT OR IGNORE INTO extracted_character_sources (name, scene_filename)
               VALUES (?, ?)""",
            (name, scene_filename),
        )
        conn.commit()

    @staticmethod
    def upsert_term_source(
        conn: sqlite3.Connection,
        term: str,
        scene_filename: str,
    ) -> None:
        """Record that term *term* was sourced from *scene_filename*."""
        conn.execute(
            """INSERT OR IGNORE INTO extracted_term_sources (term, scene_filename)
               VALUES (?, ?)""",
            (term, scene_filename),
        )
        conn.commit()

    @staticmethod
    def load_character_scenes(conn: sqlite3.Connection, name: str) -> list[str]:
        """Return all scene filenames that sourced character *name*."""
        rows = conn.execute(
            """SELECT scene_filename FROM extracted_character_sources
               WHERE name = ? ORDER BY scene_filename""",
            (name,),
        ).fetchall()
        return [row["scene_filename"] for row in rows]

    @staticmethod
    def load_term_scenes(conn: sqlite3.Connection, term: str) -> list[str]:
        """Return all scene filenames that sourced term *term*."""
        rows = conn.execute(
            """SELECT scene_filename FROM extracted_term_sources
               WHERE term = ? ORDER BY scene_filename""",
            (term,),
        ).fetchall()
        return [row["scene_filename"] for row in rows]

    @staticmethod
    def find_orphaned_characters(conn: sqlite3.Connection) -> list[str]:
        """Return character names that have no rows in extracted_character_sources.

        After a scene is re-extracted, old source rows for that scene are deleted
        and only newly-found characters are re-inserted.  A character with zero
        remaining source rows is no longer present in *any* scene and is a safe
        candidate for removal from the knowledge DB.
        """
        rows = conn.execute(
            """SELECT name FROM extracted_characters
               WHERE name NOT IN (SELECT name FROM extracted_character_sources)
               ORDER BY name"""
        ).fetchall()
        return [row["name"] for row in rows]

    @staticmethod
    def find_orphaned_terms(conn: sqlite3.Connection) -> list[str]:
        """Return term strings that have no rows in extracted_term_sources.

        Mirrors find_orphaned_characters — terms with zero source scenes are
        no longer present in any scene text and are candidates for removal.
        """
        rows = conn.execute(
            """SELECT term FROM extracted_terms
               WHERE term NOT IN (SELECT term FROM extracted_term_sources)
               ORDER BY term"""
        ).fetchall()
        return [row["term"] for row in rows]

    @staticmethod
    def upsert_thread(
        conn: sqlite3.Connection,
        thread_id: str,
        question: str | None = None,
        status: str | None = None,
        opened_in: str | None = None,
        last_advanced: str | None = None,
        resolved_in: str | None = None,
        notes: str | None = None,
        last_updated: str | None = None,
    ) -> None:
        """Insert or update an aggregated thread extraction row."""
        resolved_last_updated = last_updated or datetime.now(timezone.utc).isoformat()

        conn.execute(
            """INSERT INTO extracted_threads (
                   thread_id,
                   question,
                   status,
                   opened_in,
                   last_advanced,
                   resolved_in,
                   notes,
                   last_updated
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(thread_id) DO UPDATE SET
                   question = excluded.question,
                   status = excluded.status,
                   opened_in = excluded.opened_in,
                   last_advanced = excluded.last_advanced,
                   resolved_in = excluded.resolved_in,
                   notes = excluded.notes,
                   last_updated = excluded.last_updated""",
            (
                thread_id,
                question,
                status,
                opened_in,
                last_advanced,
                resolved_in,
                notes,
                resolved_last_updated,
            ),
        )
        conn.commit()

    @staticmethod
    def upsert_thread_event(
        conn: sqlite3.Connection,
        thread_id: str,
        scene_filename: str,
        event_type: str,
        notes: str | None = None,
    ) -> None:
        """Insert or update a per-scene thread event row."""
        conn.execute(
            """INSERT INTO extracted_thread_events (
                   thread_id,
                   scene_filename,
                   event_type,
                   notes
               ) VALUES (?, ?, ?, ?)
               ON CONFLICT(thread_id, scene_filename) DO UPDATE SET
                   event_type = excluded.event_type,
                   notes = excluded.notes""",
            (thread_id, scene_filename, event_type, notes),
        )
        conn.commit()

    @staticmethod
    def delete_thread(conn: sqlite3.Connection, thread_id: str) -> bool:
        """Delete a thread extraction row. Returns True if a row was removed."""
        cursor = conn.execute(
            "DELETE FROM extracted_threads WHERE thread_id = ?", (thread_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def load_all_threads(conn: sqlite3.Connection) -> list[dict]:
        """Load all aggregated thread rows ordered by thread id."""
        rows = conn.execute(
            "SELECT * FROM extracted_threads ORDER BY thread_id"
        ).fetchall()
        return [ExtractionStore._row_to_dict(row) for row in rows]

    @staticmethod
    def load_thread_events(
        conn: sqlite3.Connection,
        thread_id: str | None = None,
    ) -> list[dict]:
        """Load thread event rows, optionally filtered by thread id."""
        if thread_id is not None:
            rows = conn.execute(
                """SELECT * FROM extracted_thread_events
                   WHERE thread_id = ?
                   ORDER BY scene_filename""",
                (thread_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM extracted_thread_events
                   ORDER BY thread_id, scene_filename"""
            ).fetchall()
        return [ExtractionStore._row_to_dict(row) for row in rows]

    @staticmethod
    def upsert_timeline(
        conn: sqlite3.Connection,
        scene_filename: str,
        summary: str,
        chrono_hint: str | None = None,
        last_updated: str | None = None,
    ) -> None:
        """Insert or update a per-scene timeline extraction row."""
        resolved_last_updated = last_updated or datetime.now(timezone.utc).isoformat()

        conn.execute(
            """INSERT INTO extracted_timeline (
                   scene_filename,
                   summary,
                   chrono_hint,
                   last_updated
               ) VALUES (?, ?, ?, ?)
               ON CONFLICT(scene_filename) DO UPDATE SET
                   summary = excluded.summary,
                   chrono_hint = excluded.chrono_hint,
                   last_updated = excluded.last_updated""",
            (scene_filename, summary, chrono_hint, resolved_last_updated),
        )
        conn.commit()

    @staticmethod
    def delete_timeline_entry(conn: sqlite3.Connection, scene_filename: str) -> bool:
        """Delete a timeline extraction row. Returns True if a row was removed."""
        cursor = conn.execute(
            "DELETE FROM extracted_timeline WHERE scene_filename = ?", (scene_filename,)
        )
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def load_all_timeline(conn: sqlite3.Connection) -> list[dict]:
        """Load all timeline rows ordered by scene filename."""
        rows = conn.execute(
            "SELECT * FROM extracted_timeline ORDER BY scene_filename"
        ).fetchall()
        return [ExtractionStore._row_to_dict(row) for row in rows]

    @staticmethod
    def mark_scene_stale(
        conn: sqlite3.Connection,
        scene_filename: str,
        content_hash: str | None = None,
    ) -> None:
        """Mark a scene's extraction status as stale."""
        row = conn.execute(
            "SELECT content_hash FROM extracted_scene_metadata WHERE scene_filename = ?",
            (scene_filename,),
        ).fetchone()
        if row is None:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO extracted_scene_metadata (
                       scene_filename,
                       content_hash,
                       extracted_at,
                       extract_status,
                       extraction_locked,
                       locked_at
                   ) VALUES (?, ?, ?, 'stale', 0, NULL)""",
                (scene_filename, content_hash or "", now),
            )
            conn.commit()
            return

        conn.execute(
            """UPDATE extracted_scene_metadata
               SET content_hash = ?, extract_status = 'stale'
               WHERE scene_filename = ?""",
            (content_hash if content_hash is not None else row["content_hash"], scene_filename),
        )
        conn.commit()

    @staticmethod
    def lock_scene(conn: sqlite3.Connection, scene_filename: str) -> None:
        """Lock a scene to skip automatic re-extraction."""
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO extracted_scene_metadata (
                   scene_filename,
                   content_hash,
                   extracted_at,
                   extract_status,
                   extraction_locked,
                   locked_at
               ) VALUES (?, '', ?, 'stale', 1, ?)
               ON CONFLICT(scene_filename) DO UPDATE SET
                   extraction_locked = 1,
                   locked_at = excluded.locked_at""",
            (scene_filename, now, now),
        )
        conn.commit()

    @staticmethod
    def unlock_scene(conn: sqlite3.Connection, scene_filename: str) -> None:
        """Unlock a scene so automatic re-extraction can run again."""
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO extracted_scene_metadata (
                   scene_filename,
                   content_hash,
                   extracted_at,
                   extract_status,
                   extraction_locked,
                   locked_at
               ) VALUES (?, '', ?, 'stale', 0, NULL)
               ON CONFLICT(scene_filename) DO UPDATE SET
                   extraction_locked = 0,
                   locked_at = NULL""",
            (scene_filename, now),
        )
        conn.commit()

    # --- Entity locking (characters, terms, threads, timeline) ---

    _ENTITY_TABLE_MAP: dict[str, tuple[str, str]] = {
        "characters": ("extracted_characters", "name"),
        "terms": ("extracted_terms", "term"),
        "threads": ("extracted_threads", "thread_id"),
        "timeline": ("extracted_timeline", "scene_filename"),
    }

    @staticmethod
    def lock_entity(conn: sqlite3.Connection, category: str, entity_key: str) -> None:
        """Lock a knowledge entity to prevent LLM updates and deletion."""
        table, key_col = ExtractionStore._ENTITY_TABLE_MAP[category]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            f"UPDATE {table} SET entity_locked = 1, locked_at = ? WHERE {key_col} = ?",
            (now, entity_key),
        )
        conn.commit()

    @staticmethod
    def unlock_entity(conn: sqlite3.Connection, category: str, entity_key: str) -> None:
        """Unlock a knowledge entity so it can be updated by the LLM."""
        table, key_col = ExtractionStore._ENTITY_TABLE_MAP[category]
        conn.execute(
            f"UPDATE {table} SET entity_locked = 0, locked_at = NULL WHERE {key_col} = ?",
            (entity_key,),
        )
        conn.commit()

    @staticmethod
    def is_entity_locked(conn: sqlite3.Connection, category: str, entity_key: str) -> bool:
        """Return True if the given entity is locked."""
        table, key_col = ExtractionStore._ENTITY_TABLE_MAP[category]
        row = conn.execute(
            f"SELECT entity_locked FROM {table} WHERE {key_col} = ?",
            (entity_key,),
        ).fetchone()
        return bool(row["entity_locked"]) if row is not None else False

    @staticmethod
    def get_entity_lock_status(conn: sqlite3.Connection, category: str) -> dict[str, bool]:
        """Return a mapping of entity_key → locked (bool) for all entities in category."""
        table, key_col = ExtractionStore._ENTITY_TABLE_MAP[category]
        rows = conn.execute(f"SELECT {key_col}, entity_locked FROM {table}").fetchall()
        return {row[key_col]: bool(row["entity_locked"]) for row in rows}

    @staticmethod
    def reset(conn: sqlite3.Connection) -> None:
        """Bulk-delete all extracted knowledge rows across all extraction tables."""
        tables = [
            "extracted_character_sources",
            "extracted_term_sources",
            "extracted_thread_events",
            "extracted_characters",
            "extracted_terms",
            "extracted_threads",
            "extracted_timeline",
            "extracted_scene_metadata",
        ]
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

    @staticmethod
    def _serialize_json(value: str | list | dict | None) -> str | None:
        """Serialize JSON-like values while preserving string and None inputs."""
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a row into a dictionary with JSON fields parsed when possible."""
        data = dict(row)
        for field in (
            "cast_present",
            "cont_anchors",
            "aka",
            "traits",
            "relationships",
        ):
            raw_value = data.get(field)
            if isinstance(raw_value, str):
                try:
                    data[field] = json.loads(raw_value)
                except (json.JSONDecodeError, TypeError):
                    pass
        return data


__all__ = ["ExtractionStore"]
