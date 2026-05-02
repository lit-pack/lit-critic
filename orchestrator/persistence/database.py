"""Platform-owned SQLite database primitives."""

import json
import logging
import sqlite3
from pathlib import Path

from orchestrator.runtime.config import DB_FILE

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 23


def get_db_path(project_path: Path) -> Path:
    """Return the path to the project's SQLite database."""
    return project_path / DB_FILE


def get_connection(project_path: Path) -> sqlite3.Connection:
    """Open (or create) the project database and ensure the schema exists.

    Returns a ``sqlite3.Connection`` with WAL mode and foreign keys enabled.
    The caller is responsible for closing the connection.
    """
    db_path = get_db_path(project_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    _migrate_relativize_paths(conn, project_path)
    return conn


def get_passive_connection(project_path: Path) -> sqlite3.Connection | None:
    """Open an existing project database without initialization side effects.

    This startup-safe path avoids WAL setup, schema initialization, and
    migrations. If the database file does not exist yet, ``None`` is returned
    so passive reads do not create a database as a side effect.

    The returned connection is configured for row access and query-only mode.
    The caller is responsible for closing the connection.
    """
    db_path = get_db_path(project_path)
    if not db_path.exists():
        return None

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist and apply migrations."""
    conn.executescript(_SCHEMA_SQL)

    # Check / set schema version
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] if row[0] is not None else 0

    # Defensive migration path:
    # - Upgrade v1 -> v2 by dropping the legacy session.skip_minor column.
    # - Also run the migration when schema_version is already 2 but the column
    #   still exists (e.g. from an interrupted/partial upgrade).
    needs_skip_minor_drop = _table_has_column(conn, "session", "skip_minor")
    if current < 2 or needs_skip_minor_drop:
        _migrate_drop_skip_minor(conn)

    has_legacy_lens_preferences = _table_has_column(conn, "session", "lens_preferences")
    needs_lens_preferences = not has_legacy_lens_preferences
    # ``lens_preferences`` existed only in schema v3-v7 and was removed in v8.
    # Do not resurrect it for modern schemas (>= v8), otherwise every
    # connection would re-add then re-drop the column, rewriting ``session``.
    if current < 8 and needs_lens_preferences:
        _migrate_add_lens_preferences(conn)

    needs_finding_scene_path = not _table_has_column(conn, "finding", "scene_path")
    if current < 4 or needs_finding_scene_path:
        _migrate_add_finding_scene_path(conn)

    needs_index_context_hash = not _table_has_column(conn, "session", "index_context_hash")
    needs_index_context_stale = not _table_has_column(conn, "session", "index_context_stale")
    needs_index_rerun_prompted = not _table_has_column(conn, "session", "index_rerun_prompted")
    needs_index_changed_files = not _table_has_column(conn, "session", "index_changed_files")
    if (
        current < 5
        or needs_index_context_hash
        or needs_index_context_stale
        or needs_index_rerun_prompted
        or needs_index_changed_files
    ):
        _migrate_add_index_context_fields(conn)

    needs_learning_confidence = not _table_has_column(conn, "learning_entry", "confidence")
    # session_summary was added in v6 but intentionally dropped in v21.  At v21+
    # the column is correctly absent — guard against re-adding it here so we
    # don't create a circular: v6 adds it → v21 drops it → v6 re-adds it → …
    needs_session_summary = not _table_has_column(conn, "session", "session_summary") and current < 21
    if current < 6 or needs_learning_confidence or needs_session_summary:
        _migrate_add_confidence_and_session_summary(conn)

    needs_finding_origin = not _table_has_column(conn, "finding", "origin")
    if current < 7 or needs_finding_origin:
        _migrate_add_finding_origin(conn)

    if current < 8 or has_legacy_lens_preferences:
        _migrate_drop_lens_preferences(conn)

    needs_depth_mode = not _table_has_column(conn, "session", "depth_mode")
    needs_frontier_model = not _table_has_column(conn, "session", "frontier_model")
    needs_checker_model = not _table_has_column(conn, "session", "checker_model")
    if current < 9 or needs_depth_mode or needs_frontier_model or needs_checker_model:
        _migrate_add_tier_model_fields(conn)

    needs_scene_projection = not _table_exists(conn, "scene_projection")
    if current < 10 or needs_scene_projection:
        _migrate_add_scene_projection(conn)

    needs_index_projection = not _table_exists(conn, "index_projection")
    if current < 11 or needs_index_projection:
        _migrate_add_index_projection(conn)

    needs_extracted_scene_metadata = not _table_exists(
        conn, "extracted_scene_metadata"
    )
    needs_extracted_characters = not _table_exists(conn, "extracted_characters")
    needs_extracted_terms = not _table_exists(conn, "extracted_terms")
    needs_extracted_threads = not _table_exists(conn, "extracted_threads")
    needs_extracted_thread_events = not _table_exists(conn, "extracted_thread_events")
    needs_extracted_timeline = not _table_exists(conn, "extracted_timeline")
    needs_knowledge_overrides = not _table_exists(conn, "knowledge_overrides")
    if (
        current < 12
        or needs_extracted_scene_metadata
        or needs_extracted_characters
        or needs_extracted_terms
        or needs_extracted_threads
        or needs_extracted_thread_events
        or needs_extracted_timeline
        or needs_knowledge_overrides
    ):
        _migrate_add_extracted_knowledge(conn)

    needs_entity_locked_characters = not _table_has_column(conn, "extracted_characters", "entity_locked")
    needs_entity_locked_terms = not _table_has_column(conn, "extracted_terms", "entity_locked")
    needs_entity_locked_threads = not _table_has_column(conn, "extracted_threads", "entity_locked")
    needs_entity_locked_timeline = not _table_has_column(conn, "extracted_timeline", "entity_locked")
    if (
        current < 14
        or needs_entity_locked_characters
        or needs_entity_locked_terms
        or needs_entity_locked_threads
        or needs_entity_locked_timeline
    ):
        _migrate_add_entity_locking(conn)

    needs_character_sources = not _table_exists(conn, "extracted_character_sources")
    needs_term_sources = not _table_exists(conn, "extracted_term_sources")
    if current < 15 or needs_character_sources or needs_term_sources:
        _migrate_add_source_tables(conn)

    needs_review_flags = not _table_exists(conn, "knowledge_review_flags")
    if current < 16 or needs_review_flags:
        _migrate_add_knowledge_review_flags(conn)

    needs_staleness_cache = not _table_exists(conn, "knowledge_staleness_cache")
    if current < 17 or needs_staleness_cache:
        _migrate_add_knowledge_staleness_cache(conn)

    needs_editorial_profile = not _table_has_column(conn, "learning", "editorial_profile")
    if current < 18 or needs_editorial_profile:
        _migrate_add_editorial_profile(conn)

    needs_analysis_snapshot = not _table_exists(conn, "analysis_snapshot")
    if current < 19 or needs_analysis_snapshot:
        _migrate_add_analysis_snapshot(conn)

    needs_silence_rule = not _table_exists(conn, "silence_rule")
    if current < 20 or needs_silence_rule:
        _migrate_add_silence_rule(conn)

    needs_deprecated_column_drop = (
        _table_has_column(conn, "session", "current_index")
        or _table_has_column(conn, "session", "discussion_history")
        or _table_has_column(conn, "session", "session_summary")
        or _table_has_column(conn, "finding", "author_response")
    )
    if current < 21 or needs_deprecated_column_drop:
        _migrate_v21_drop_deprecated_columns(conn)

    needs_session_finding_drop = _table_exists(conn, "session") or _table_exists(conn, "finding")
    if current < 22 or needs_session_finding_drop:
        _migrate_v22_drop_session_finding(conn)

    needs_source_file_hash = (
        _table_exists(conn, "analysis_snapshot")
        and not _table_has_column(conn, "analysis_snapshot", "source_file_hash")
    )
    if current < 23 or needs_source_file_hash:
        _migrate_v23_add_source_file_hash(conn)

    if current < SCHEMA_VERSION:
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if *table* contains *column*."""
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c[1] == column for c in cols)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return True if *table* exists in the current database."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _migrate_drop_skip_minor(conn: sqlite3.Connection) -> None:
    """Drop the legacy ``session.skip_minor`` column while preserving data."""
    if not _table_has_column(conn, "session", "skip_minor"):
        return

    logger.info("Applying DB migration: drop session.skip_minor")
    conn.execute("BEGIN")
    try:
        conn.execute(
            """CREATE TABLE session_new (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   scene_path TEXT NOT NULL,
                   scene_hash TEXT NOT NULL,
                   model TEXT NOT NULL,
                   discussion_model TEXT,
                   lens_preferences TEXT DEFAULT '{}',
                   current_index INTEGER DEFAULT 0,
                   status TEXT DEFAULT 'active',
                   glossary_issues TEXT DEFAULT '[]',
                   discussion_history TEXT DEFAULT '[]',
                   learning_session TEXT DEFAULT '{}',
                   created_at TEXT NOT NULL,
                   completed_at TEXT,
                   total_findings INTEGER DEFAULT 0,
                   accepted_count INTEGER DEFAULT 0,
                   rejected_count INTEGER DEFAULT 0,
                   withdrawn_count INTEGER DEFAULT 0
               )"""
        )

        conn.execute(
            """INSERT INTO session_new (
                   id, scene_path, scene_hash, model, discussion_model,
                   lens_preferences,
                   current_index, status, glossary_issues, discussion_history,
                   learning_session, created_at, completed_at, total_findings,
                   accepted_count, rejected_count, withdrawn_count
               )
               SELECT
                   id, scene_path, scene_hash, model, discussion_model,
                   '{}',
                   current_index, status, glossary_issues, discussion_history,
                   learning_session, created_at, completed_at, total_findings,
                   accepted_count, rejected_count, withdrawn_count
               FROM session"""
        )

        conn.execute("DROP TABLE session")
        conn.execute("ALTER TABLE session_new RENAME TO session")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _migrate_add_lens_preferences(conn: sqlite3.Connection) -> None:
    """Add ``session.lens_preferences`` when missing."""
    if not _table_exists(conn, "session"):
        return
    if _table_has_column(conn, "session", "lens_preferences"):
        return

    logger.info("Applying DB migration: add session.lens_preferences")
    conn.execute("ALTER TABLE session ADD COLUMN lens_preferences TEXT DEFAULT '{}' ")
    conn.execute("UPDATE session SET lens_preferences = '{}' WHERE lens_preferences IS NULL")
    conn.commit()


def _migrate_add_finding_scene_path(conn: sqlite3.Connection) -> None:
    """Add ``finding.scene_path`` when missing."""
    if not _table_exists(conn, "finding"):
        return
    if _table_has_column(conn, "finding", "scene_path"):
        return

    logger.info("Applying DB migration: add finding.scene_path")
    conn.execute("ALTER TABLE finding ADD COLUMN scene_path TEXT")
    conn.commit()


def _migrate_add_index_context_fields(conn: sqlite3.Connection) -> None:
    """Add index-context stale detection columns to ``session`` when missing."""
    if not _table_exists(conn, "session"):
        return
    needs_hash = not _table_has_column(conn, "session", "index_context_hash")
    needs_stale = not _table_has_column(conn, "session", "index_context_stale")
    needs_prompted = not _table_has_column(conn, "session", "index_rerun_prompted")
    needs_changed = not _table_has_column(conn, "session", "index_changed_files")
    if not any([needs_hash, needs_stale, needs_prompted, needs_changed]):
        logger.debug("DB migration already applied: add session index-context fields")
        return
    logger.info("Applying DB migration: add session index-context fields")
    if needs_hash:
        conn.execute("ALTER TABLE session ADD COLUMN index_context_hash TEXT DEFAULT ''")
    if needs_stale:
        conn.execute("ALTER TABLE session ADD COLUMN index_context_stale INTEGER DEFAULT 0")
    if needs_prompted:
        conn.execute("ALTER TABLE session ADD COLUMN index_rerun_prompted INTEGER DEFAULT 0")
    if needs_changed:
        conn.execute("ALTER TABLE session ADD COLUMN index_changed_files TEXT DEFAULT '[]'")
    conn.commit()


def _migrate_add_finding_origin(conn: sqlite3.Connection) -> None:
    """Add ``finding.origin`` when missing (v7 — tiered analysis architecture)."""
    if not _table_exists(conn, "finding"):
        return
    if _table_has_column(conn, "finding", "origin"):
        return

    logger.info("Applying DB migration: add finding.origin")
    conn.execute("ALTER TABLE finding ADD COLUMN origin TEXT DEFAULT 'legacy'")
    conn.execute("UPDATE finding SET origin = 'legacy' WHERE origin IS NULL")
    conn.commit()


def _migrate_drop_lens_preferences(conn: sqlite3.Connection) -> None:
    """Drop legacy ``session.lens_preferences`` column (v8 cleanup)."""
    if not _table_has_column(conn, "session", "lens_preferences"):
        return

    logger.info("Applying DB migration: drop session.lens_preferences")

    # Deprecated columns (removed in v21) may already be absent on fresh v21 databases.
    # Only include them in session_new when they actually exist in the source table.
    deprecated = [
        (c, t) for c, t in [
            ("current_index", "INTEGER DEFAULT 0"),
            ("discussion_history", "TEXT DEFAULT '[]'"),
            ("learning_session", "TEXT DEFAULT '{}'"),
            ("session_summary", "TEXT DEFAULT ''"),
        ]
        if _table_has_column(conn, "session", c)
    ]
    extra_ddl = "".join(f",\n                   {c} {t}" for c, t in deprecated)
    extra_cols = "".join(f",\n                   {c}" for c, _ in deprecated)

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    try:
        conn.execute(
            f"""CREATE TABLE session_new (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   scene_path TEXT NOT NULL,
                   scene_hash TEXT NOT NULL,
                   model TEXT NOT NULL,
                   discussion_model TEXT,
                   status TEXT DEFAULT 'active',
                   glossary_issues TEXT DEFAULT '[]',
                   created_at TEXT NOT NULL,
                   completed_at TEXT,
                   total_findings INTEGER DEFAULT 0,
                   accepted_count INTEGER DEFAULT 0,
                   rejected_count INTEGER DEFAULT 0,
                   withdrawn_count INTEGER DEFAULT 0,
                   index_context_hash TEXT DEFAULT '',
                   index_context_stale INTEGER DEFAULT 0,
                   index_rerun_prompted INTEGER DEFAULT 0,
                   index_changed_files TEXT DEFAULT '[]'{extra_ddl}
               )"""
        )
        conn.execute(
            f"""INSERT INTO session_new (
                   id, scene_path, scene_hash, model, discussion_model,
                   status, glossary_issues, created_at, completed_at,
                   total_findings, accepted_count, rejected_count, withdrawn_count,
                   index_context_hash, index_context_stale, index_rerun_prompted,
                   index_changed_files{extra_cols}
               )
               SELECT
                   id, scene_path, scene_hash, model, discussion_model,
                   status, glossary_issues, created_at, completed_at,
                   total_findings, accepted_count, rejected_count, withdrawn_count,
                   index_context_hash, index_context_stale, index_rerun_prompted,
                   index_changed_files{extra_cols}
               FROM session"""
        )
        conn.execute("DROP TABLE session")
        conn.execute("ALTER TABLE session_new RENAME TO session")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _migrate_add_confidence_and_session_summary(conn: sqlite3.Connection) -> None:
    """Add v6 anti-sycophancy columns for learning confidence and session summary."""
    needs_confidence = not _table_has_column(conn, "learning_entry", "confidence")
    # session table is dropped in v22; skip session_summary migration if table is gone
    needs_summary = not _table_has_column(conn, "session", "session_summary") and _table_exists(conn, "session")
    if not needs_confidence and not needs_summary:
        logger.debug("DB migration already applied: add learning confidence + session summary")
        return
    logger.info("Applying DB migration: add learning confidence + session summary")
    if needs_confidence:
        conn.execute("ALTER TABLE learning_entry ADD COLUMN confidence REAL DEFAULT 0.5")
    conn.execute(
        "UPDATE learning_entry SET confidence = 0.5 WHERE confidence IS NULL"
    )
    if needs_summary:
        conn.execute("ALTER TABLE session ADD COLUMN session_summary TEXT DEFAULT ''")
        conn.execute(
            "UPDATE session SET session_summary = '' WHERE session_summary IS NULL"
        )
    conn.commit()


def _migrate_add_tier_model_fields(conn: sqlite3.Connection) -> None:
    """Add tier-model assignment columns to ``session`` when missing (v9)."""
    if not _table_exists(conn, "session"):
        return
    needs_depth = not _table_has_column(conn, "session", "depth_mode")
    needs_frontier = not _table_has_column(conn, "session", "frontier_model")
    needs_checker = not _table_has_column(conn, "session", "checker_model")
    if not any([needs_depth, needs_frontier, needs_checker]):
        logger.debug("DB migration already applied: add session tier model fields")
        return
    logger.info("Applying DB migration: add session tier model fields")
    if needs_depth:
        conn.execute("ALTER TABLE session ADD COLUMN depth_mode TEXT DEFAULT 'deep'")
    if needs_frontier:
        conn.execute("ALTER TABLE session ADD COLUMN frontier_model TEXT DEFAULT ''")
    if needs_checker:
        conn.execute("ALTER TABLE session ADD COLUMN checker_model TEXT DEFAULT ''")

    conn.execute(
        "UPDATE session SET depth_mode = 'deep' WHERE depth_mode IS NULL OR depth_mode = ''"
    )
    conn.execute(
        "UPDATE session SET checker_model = model "
        "WHERE checker_model IS NULL OR checker_model = ''"
    )
    conn.execute(
        "UPDATE session "
        "SET frontier_model = COALESCE(NULLIF(discussion_model, ''), model) "
        "WHERE frontier_model IS NULL OR frontier_model = ''"
    )
    conn.commit()


def _migrate_add_scene_projection(conn: sqlite3.Connection) -> None:
    """Add ``scene_projection`` table when missing (v10)."""
    logger.info("Applying DB migration: add scene_projection table")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scene_projection (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               scene_path TEXT NOT NULL UNIQUE,
               scene_id TEXT,
               file_hash TEXT NOT NULL,
               meta_json TEXT NOT NULL DEFAULT '{}',
               last_refreshed_at TEXT NOT NULL
           )"""
    )
    conn.commit()


def _migrate_add_index_projection(conn: sqlite3.Connection) -> None:
    """Add ``index_projection`` table when missing (v11)."""
    logger.info("Applying DB migration: add index_projection table")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS index_projection (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               index_name TEXT NOT NULL UNIQUE,
               file_hash TEXT NOT NULL,
               entries_json TEXT,
               raw_content_hash TEXT NOT NULL,
               last_refreshed_at TEXT NOT NULL
           )"""
    )
    conn.commit()


def _migrate_add_extracted_knowledge(conn: sqlite3.Connection) -> None:
    """Add extracted-knowledge tables when missing (v12)."""
    logger.info("Applying DB migration: add extracted knowledge tables")

    if not _table_exists(conn, "extracted_scene_metadata"):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS extracted_scene_metadata (
                   scene_filename TEXT NOT NULL PRIMARY KEY,
                   content_hash TEXT NOT NULL,
                   extracted_at TEXT NOT NULL,
                   location TEXT,
                   pov TEXT,
                   tense TEXT,
                   tense_notes TEXT,
                   cast_present TEXT,
                   objective TEXT,
                   cont_anchors TEXT,
                   extract_status TEXT NOT NULL DEFAULT 'ok',
                   extraction_locked INTEGER NOT NULL DEFAULT 0,
                   locked_at TEXT
               )"""
        )

    if not _table_exists(conn, "extracted_characters"):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS extracted_characters (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL UNIQUE,
                   aka TEXT,
                   category TEXT,
                   traits TEXT,
                   relationships TEXT,
                   first_seen TEXT,
                   last_updated TEXT NOT NULL
               )"""
        )

    if not _table_exists(conn, "extracted_terms"):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS extracted_terms (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   term TEXT NOT NULL UNIQUE,
                   category TEXT,
                   definition TEXT,
                   translation TEXT,
                   notes TEXT,
                   first_seen TEXT,
                   last_updated TEXT NOT NULL
               )"""
        )

    if not _table_exists(conn, "extracted_threads"):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS extracted_threads (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   thread_id TEXT NOT NULL UNIQUE,
                   question TEXT,
                   status TEXT,
                   opened_in TEXT,
                   last_advanced TEXT,
                   resolved_in TEXT,
                   notes TEXT,
                   last_updated TEXT NOT NULL
               )"""
        )

    if not _table_exists(conn, "extracted_thread_events"):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS extracted_thread_events (
                   thread_id TEXT NOT NULL,
                   scene_filename TEXT NOT NULL,
                   event_type TEXT NOT NULL,
                   notes TEXT,
                   PRIMARY KEY (thread_id, scene_filename)
               )"""
        )

    if not _table_exists(conn, "extracted_timeline"):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS extracted_timeline (
                   scene_filename TEXT NOT NULL PRIMARY KEY,
                   summary TEXT NOT NULL,
                   chrono_hint TEXT,
                   last_updated TEXT NOT NULL
               )"""
        )

    if not _table_exists(conn, "knowledge_overrides"):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_overrides (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   category TEXT NOT NULL,
                   entity_key TEXT NOT NULL,
                   field_name TEXT NOT NULL,
                   override_value TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   UNIQUE(category, entity_key, field_name)
               )"""
        )

    conn.commit()


def _migrate_add_entity_locking(conn: sqlite3.Connection) -> None:
    """Add ``entity_locked`` and ``locked_at`` columns to entity tables (v14)."""
    logger.info("Applying DB migration: add entity_locked columns")
    for table in ("extracted_characters", "extracted_terms", "extracted_threads", "extracted_timeline"):
        if not _table_has_column(conn, table, "entity_locked"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN entity_locked INTEGER NOT NULL DEFAULT 0")
        if not _table_has_column(conn, table, "locked_at"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN locked_at TEXT")
    conn.commit()


def _migrate_add_source_tables(conn: sqlite3.Connection) -> None:
    """Add character/term provenance source junction tables when missing (v15)."""
    logger.info("Applying DB migration: add extracted source junction tables")
    if not _table_exists(conn, "extracted_character_sources"):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS extracted_character_sources (
                   name TEXT NOT NULL,
                   scene_filename TEXT NOT NULL,
                   PRIMARY KEY (name, scene_filename)
               )"""
        )
    if not _table_exists(conn, "extracted_term_sources"):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS extracted_term_sources (
                   term TEXT NOT NULL,
                   scene_filename TEXT NOT NULL,
                   PRIMARY KEY (term, scene_filename)
               )"""
        )
    conn.commit()


def _migrate_add_knowledge_review_flags(conn: sqlite3.Connection) -> None:
    """Add ``knowledge_review_flags`` table when missing (v16)."""
    logger.info("Applying DB migration: add knowledge_review_flags table")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS knowledge_review_flags (
               category    TEXT NOT NULL,
               entity_key  TEXT NOT NULL,
               reason      TEXT NOT NULL DEFAULT '',
               flagged_at  TEXT NOT NULL,
               PRIMARY KEY (category, entity_key)
           )"""
    )
    conn.commit()


def _migrate_add_knowledge_staleness_cache(conn: sqlite3.Connection) -> None:
    """Add ``knowledge_staleness_cache`` table when missing (v17)."""
    logger.info("Applying DB migration: add knowledge_staleness_cache table")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS knowledge_staleness_cache (
               category    TEXT NOT NULL,
               entity_key  TEXT NOT NULL,
               source_path TEXT NOT NULL DEFAULT '',
               cached_at   TEXT NOT NULL,
               PRIMARY KEY (category, entity_key)
           )"""
    )
    conn.commit()


def _migrate_add_editorial_profile(conn: sqlite3.Connection) -> None:
    """Add ``editorial_profile`` and ``editorial_profile_updated_at`` columns to ``learning`` (v18)."""
    logger.info("Applying DB migration: add learning.editorial_profile columns")
    if not _table_has_column(conn, "learning", "editorial_profile"):
        conn.execute("ALTER TABLE learning ADD COLUMN editorial_profile TEXT")
    if not _table_has_column(conn, "learning", "editorial_profile_updated_at"):
        conn.execute("ALTER TABLE learning ADD COLUMN editorial_profile_updated_at TEXT")
    conn.commit()


def _migrate_add_analysis_snapshot(conn: sqlite3.Connection) -> None:
    """Add ``analysis_snapshot`` and ``snapshot_finding`` tables (v19)."""
    logger.info("Applying DB migration: add analysis_snapshot and snapshot_finding tables")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS analysis_snapshot (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               scene_paths TEXT NOT NULL DEFAULT '[]',
               depth_mode TEXT NOT NULL DEFAULT 'quick',
               frontier_model TEXT DEFAULT '',
               checker_model TEXT DEFAULT '',
               quick_model TEXT DEFAULT '',
               scene_hashes TEXT NOT NULL DEFAULT '{}',
               index_context_hash TEXT DEFAULT '',
               created_at TEXT NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS snapshot_finding (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               snapshot_id INTEGER NOT NULL REFERENCES analysis_snapshot(id) ON DELETE CASCADE,
               number INTEGER NOT NULL,
               severity TEXT NOT NULL,
               lens TEXT NOT NULL,
               location TEXT DEFAULT '',
               line_start INTEGER,
               line_end INTEGER,
               scene_path TEXT DEFAULT '',
               evidence TEXT DEFAULT '',
               impact TEXT DEFAULT '',
               options TEXT DEFAULT '[]',
               flagged_by TEXT DEFAULT '[]',
               ambiguity_type TEXT,
               state TEXT DEFAULT 'active',
               correlation_key TEXT DEFAULT ''
           )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshot_finding_snapshot ON snapshot_finding(snapshot_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshot_finding_state ON snapshot_finding(snapshot_id, state)"
    )
    conn.commit()


def _migrate_add_silence_rule(conn: sqlite3.Connection) -> None:
    """Add ``silence_rule`` table (v20)."""
    logger.info("Applying DB migration: add silence_rule table")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS silence_rule (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               rule_type TEXT NOT NULL,
               scope TEXT NOT NULL DEFAULT 'scene',
               scene_path TEXT DEFAULT '',
               finding_id INTEGER,
               lens TEXT DEFAULT '',
               severity TEXT DEFAULT '',
               text_pattern TEXT DEFAULT '',
               note TEXT DEFAULT '',
               suspended INTEGER DEFAULT 0,
               created_at TEXT NOT NULL,
               suspended_at TEXT DEFAULT ''
           )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_silence_rule_scene ON silence_rule(scope, scene_path)"
    )
    conn.commit()


def _migrate_v21_drop_deprecated_columns(conn: sqlite3.Connection) -> None:
    """Drop deprecated interactive-session columns from ``session`` and ``finding`` (v21).

    Session columns removed: ``current_index``, ``discussion_history``,
    ``learning_session``, ``session_summary``.
    Finding columns removed: ``author_response``, ``revision_history``,
    ``outcome_reason``.
    """
    needs_session = (
        _table_has_column(conn, "session", "current_index")
        or _table_has_column(conn, "session", "discussion_history")
        or _table_has_column(conn, "session", "learning_session")
        or _table_has_column(conn, "session", "session_summary")
    )
    needs_finding = (
        _table_has_column(conn, "finding", "author_response")
        or _table_has_column(conn, "finding", "revision_history")
        or _table_has_column(conn, "finding", "outcome_reason")
    )

    if not needs_session and not needs_finding:
        return

    logger.info("Applying DB migration v21: drop deprecated interactive-session columns")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    try:
        if needs_session:
            conn.execute(
                """CREATE TABLE session_new (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       scene_path TEXT NOT NULL,
                       scene_hash TEXT NOT NULL,
                       model TEXT NOT NULL,
                       discussion_model TEXT,
                       depth_mode TEXT DEFAULT 'deep',
                       frontier_model TEXT DEFAULT '',
                       checker_model TEXT DEFAULT '',
                       status TEXT DEFAULT 'active',
                       glossary_issues TEXT DEFAULT '[]',
                       created_at TEXT NOT NULL,
                       completed_at TEXT,
                       total_findings INTEGER DEFAULT 0,
                       accepted_count INTEGER DEFAULT 0,
                       rejected_count INTEGER DEFAULT 0,
                       withdrawn_count INTEGER DEFAULT 0,
                       index_context_hash TEXT DEFAULT '',
                       index_context_stale INTEGER DEFAULT 0,
                       index_rerun_prompted INTEGER DEFAULT 0,
                       index_changed_files TEXT DEFAULT '[]'
                   )"""
            )
            conn.execute(
                """INSERT INTO session_new (
                       id, scene_path, scene_hash, model, discussion_model,
                       depth_mode, frontier_model, checker_model, status, glossary_issues,
                       created_at, completed_at, total_findings, accepted_count,
                       rejected_count, withdrawn_count, index_context_hash,
                       index_context_stale, index_rerun_prompted, index_changed_files
                   )
                   SELECT
                       id, scene_path, scene_hash, model, discussion_model,
                       depth_mode, frontier_model, checker_model, status, glossary_issues,
                       created_at, completed_at, total_findings, accepted_count,
                       rejected_count, withdrawn_count, index_context_hash,
                       index_context_stale, index_rerun_prompted, index_changed_files
                   FROM session"""
            )
            conn.execute("DROP TABLE session")
            conn.execute("ALTER TABLE session_new RENAME TO session")

        if needs_finding:
            conn.execute(
                """CREATE TABLE finding_new (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       session_id INTEGER NOT NULL REFERENCES session(id) ON DELETE CASCADE,
                       number INTEGER NOT NULL,
                       severity TEXT NOT NULL,
                       lens TEXT NOT NULL,
                       location TEXT DEFAULT '',
                       line_start INTEGER,
                       line_end INTEGER,
                       scene_path TEXT,
                       evidence TEXT DEFAULT '',
                       impact TEXT DEFAULT '',
                       options TEXT DEFAULT '[]',
                       flagged_by TEXT DEFAULT '[]',
                       ambiguity_type TEXT,
                       stale INTEGER DEFAULT 0,
                       status TEXT DEFAULT 'pending',
                       discussion_turns TEXT DEFAULT '[]',
                       origin TEXT DEFAULT 'legacy'
                   )"""
            )
            conn.execute(
                """INSERT INTO finding_new (
                       id, session_id, number, severity, lens, location,
                       line_start, line_end, scene_path, evidence, impact, options,
                       flagged_by, ambiguity_type, stale, status, discussion_turns, origin
                   )
                   SELECT
                       id, session_id, number, severity, lens, location,
                       line_start, line_end, scene_path, evidence, impact, options,
                       flagged_by, ambiguity_type, stale, status, discussion_turns, origin
                   FROM finding"""
            )
            conn.execute("DROP TABLE finding")
            conn.execute("ALTER TABLE finding_new RENAME TO finding")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_finding_session ON finding(session_id)"
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _migrate_v22_drop_session_finding(conn: sqlite3.Connection) -> None:
    """Drop legacy ``session`` and ``finding`` tables (v22).

    These tables are superseded by ``analysis_snapshot`` + ``snapshot_finding``.
    Nothing writes to them after Task 3 (user-triggered analysis now produces
    snapshots). This migration removes them from all existing databases.
    """
    if not _table_exists(conn, "session") and not _table_exists(conn, "finding"):
        return

    logger.info("Applying DB migration v22: drop session and finding tables")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("BEGIN")
    try:
        conn.execute("DROP TABLE IF EXISTS finding")
        conn.execute("DROP TABLE IF EXISTS session")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _migrate_v23_add_source_file_hash(conn: sqlite3.Connection) -> None:
    """Add ``source_file_hash`` column to ``analysis_snapshot`` (v23)."""
    if _table_has_column(conn, "analysis_snapshot", "source_file_hash"):
        return
    logger.info("Applying DB migration v23: add analysis_snapshot.source_file_hash")
    conn.execute(
        "ALTER TABLE analysis_snapshot ADD COLUMN source_file_hash TEXT DEFAULT ''"
    )
    conn.commit()


def _migrate_relativize_paths(conn: sqlite3.Connection, project_path: Path) -> None:
    """Rewrite absolute stored paths to project-relative POSIX strings (v13).

    Idempotent: paths already relative (or outside the project root) are left
    unchanged.  Runs only on writable connections obtained via
    ``get_connection()``; passive connections skip this entirely.

    Fast-path guard: if no row in ``scene_projection`` or ``finding`` contains
    an absolute path, the full scan is skipped silently.  This avoids
    unnecessary I/O on every ``get_connection()`` call once the DB is already
    fully relativized.
    """
    # ------------------------------------------------------------------
    # Fast-path: check whether any stored scene_path looks absolute.
    # Skip the full row scan when everything is already relativized.
    #
    # scene_projection and finding store plain strings:
    #   '?:*'  matches Windows paths (e.g. D:\...)
    #   '/*'   matches POSIX absolute paths
    #
    # session.scene_path is JSON-encoded (e.g. ["D:\\Projects\\...\\ch01.txt"])
    # so we look for a quoted character followed by ':' inside the JSON:
    #   '%"_:%'  matches Windows paths embedded in JSON
    #   '%"/%'   matches POSIX absolute paths embedded in JSON
    # ------------------------------------------------------------------
    _needs_migration = False
    for _table, _col, _where in (
        ("scene_projection", "scene_path",
         "scene_path GLOB '?:*' OR scene_path GLOB '/*'"),
        ("finding", "scene_path",
         "scene_path GLOB '?:*' OR scene_path GLOB '/*'"),
        ("session", "scene_path",
         "scene_path LIKE '%\"_:%' OR scene_path LIKE '%\"/%'"),
    ):
        try:
            _row = conn.execute(
                f"SELECT 1 FROM {_table} WHERE {_where} LIMIT 1"  # noqa: S608 — safe: no user input
            ).fetchone()
            if _row is not None:
                _needs_migration = True
                break
        except sqlite3.OperationalError:
            pass  # table may not exist yet; skip this check
    if not _needs_migration:
        return

    from orchestrator.persistence.path_utils import to_relative  # local import avoids circularity

    root = Path(project_path).resolve()

    def _rel(val: str | None) -> str:
        if not val:
            return val or ""
        return to_relative(root, val)

    def _rel_json_array(raw: str | None) -> str:
        """Relativize each element of a JSON array string."""
        if not raw:
            return raw or "[]"
        try:
            items = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
        if not isinstance(items, list):
            return raw
        return json.dumps([_rel(item) if isinstance(item, str) else item for item in items])

    logger.info("Applying DB migration v13: relativize stored paths")

    changed = False

    # --- session.scene_path (JSON-encoded list) and session.index_changed_files ---
    # Guard: session table is dropped in v22; skip if it no longer exists.
    if _table_exists(conn, "session"):
        sessions = conn.execute("SELECT id, scene_path, index_changed_files FROM session").fetchall()
        for row in sessions:
            new_scene = _rel_json_array(row["scene_path"])
            new_changed = _rel_json_array(row["index_changed_files"])
            if new_scene != row["scene_path"] or new_changed != row["index_changed_files"]:
                conn.execute(
                    "UPDATE session SET scene_path = ?, index_changed_files = ? WHERE id = ?",
                    (new_scene, new_changed, row["id"]),
                )
                changed = True

    # --- finding.scene_path (plain string) ---
    # Guard: finding table is dropped in v22; skip if it no longer exists.
    if _table_exists(conn, "finding"):
        findings = conn.execute("SELECT id, scene_path FROM finding WHERE scene_path IS NOT NULL").fetchall()
        for row in findings:
            new_path = _rel(row["scene_path"])
            if new_path != row["scene_path"]:
                conn.execute(
                    "UPDATE finding SET scene_path = ? WHERE id = ?",
                    (new_path, row["id"]),
                )
                changed = True

    # --- scene_projection.scene_path (unique key, plain string) ---
    # Use a temp-rename approach to avoid unique-constraint conflicts mid-update
    projections = conn.execute("SELECT id, scene_path FROM scene_projection").fetchall()
    for row in projections:
        new_path = _rel(row["scene_path"])
        if new_path != row["scene_path"]:
            conn.execute(
                "UPDATE scene_projection SET scene_path = ? WHERE id = ?",
                (new_path, row["id"]),
            )
            changed = True

    if changed:
        conn.commit()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS learning (
    id INTEGER PRIMARY KEY,
    project_name TEXT DEFAULT 'Unknown',
    review_count INTEGER DEFAULT 0,
    updated_at TEXT,
    editorial_profile TEXT,
    editorial_profile_updated_at TEXT
);

CREATE TABLE IF NOT EXISTS learning_entry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_id INTEGER NOT NULL REFERENCES learning(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_learning_entry_category ON learning_entry(category);

CREATE TABLE IF NOT EXISTS scene_projection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scene_path TEXT NOT NULL UNIQUE,
    scene_id TEXT,
    file_hash TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}',
    last_refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_projection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    index_name TEXT NOT NULL UNIQUE,
    file_hash TEXT NOT NULL,
    entries_json TEXT,
    raw_content_hash TEXT NOT NULL,
    last_refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extracted_scene_metadata (
    scene_filename TEXT NOT NULL PRIMARY KEY,
    content_hash TEXT NOT NULL,
    extracted_at TEXT NOT NULL,
    location TEXT,
    pov TEXT,
    tense TEXT,
    tense_notes TEXT,
    cast_present TEXT,
    objective TEXT,
    cont_anchors TEXT,
    extract_status TEXT NOT NULL DEFAULT 'ok',
    extraction_locked INTEGER NOT NULL DEFAULT 0,
    locked_at TEXT
);

CREATE TABLE IF NOT EXISTS extracted_characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    aka TEXT,
    category TEXT,
    traits TEXT,
    relationships TEXT,
    first_seen TEXT,
    last_updated TEXT NOT NULL,
    entity_locked INTEGER NOT NULL DEFAULT 0,
    locked_at TEXT
);

CREATE TABLE IF NOT EXISTS extracted_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE,
    category TEXT,
    definition TEXT,
    translation TEXT,
    notes TEXT,
    first_seen TEXT,
    last_updated TEXT NOT NULL,
    entity_locked INTEGER NOT NULL DEFAULT 0,
    locked_at TEXT
);

CREATE TABLE IF NOT EXISTS extracted_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL UNIQUE,
    question TEXT,
    status TEXT,
    opened_in TEXT,
    last_advanced TEXT,
    resolved_in TEXT,
    notes TEXT,
    last_updated TEXT NOT NULL,
    entity_locked INTEGER NOT NULL DEFAULT 0,
    locked_at TEXT
);

CREATE TABLE IF NOT EXISTS extracted_thread_events (
    thread_id TEXT NOT NULL,
    scene_filename TEXT NOT NULL,
    event_type TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (thread_id, scene_filename)
);

CREATE TABLE IF NOT EXISTS extracted_timeline (
    scene_filename TEXT NOT NULL PRIMARY KEY,
    summary TEXT NOT NULL,
    chrono_hint TEXT,
    last_updated TEXT NOT NULL,
    entity_locked INTEGER NOT NULL DEFAULT 0,
    locked_at TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    field_name TEXT NOT NULL,
    override_value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(category, entity_key, field_name)
);

CREATE TABLE IF NOT EXISTS extracted_character_sources (
    name TEXT NOT NULL,
    scene_filename TEXT NOT NULL,
    PRIMARY KEY (name, scene_filename)
);

CREATE TABLE IF NOT EXISTS extracted_term_sources (
    term TEXT NOT NULL,
    scene_filename TEXT NOT NULL,
    PRIMARY KEY (term, scene_filename)
);

CREATE TABLE IF NOT EXISTS knowledge_review_flags (
    category    TEXT NOT NULL,
    entity_key  TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    flagged_at  TEXT NOT NULL,
    PRIMARY KEY (category, entity_key)
);

CREATE TABLE IF NOT EXISTS knowledge_staleness_cache (
    category    TEXT NOT NULL,
    entity_key  TEXT NOT NULL,
    source_path TEXT NOT NULL DEFAULT '',
    cached_at   TEXT NOT NULL,
    PRIMARY KEY (category, entity_key)
);

CREATE TABLE IF NOT EXISTS analysis_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scene_paths TEXT NOT NULL DEFAULT '[]',
    depth_mode TEXT NOT NULL DEFAULT 'quick',
    frontier_model TEXT DEFAULT '',
    checker_model TEXT DEFAULT '',
    quick_model TEXT DEFAULT '',
    scene_hashes TEXT NOT NULL DEFAULT '{}',
    source_file_hash TEXT DEFAULT '',
    index_context_hash TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_finding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES analysis_snapshot(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    severity TEXT NOT NULL,
    lens TEXT NOT NULL,
    location TEXT DEFAULT '',
    line_start INTEGER,
    line_end INTEGER,
    scene_path TEXT DEFAULT '',
    evidence TEXT DEFAULT '',
    impact TEXT DEFAULT '',
    options TEXT DEFAULT '[]',
    flagged_by TEXT DEFAULT '[]',
    ambiguity_type TEXT,
    state TEXT DEFAULT 'active',
    correlation_key TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_snapshot_finding_snapshot ON snapshot_finding(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_finding_state ON snapshot_finding(snapshot_id, state);

CREATE TABLE IF NOT EXISTS silence_rule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'scene',
    scene_path TEXT DEFAULT '',
    finding_id INTEGER,
    lens TEXT DEFAULT '',
    severity TEXT DEFAULT '',
    text_pattern TEXT DEFAULT '',
    note TEXT DEFAULT '',
    suspended INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    suspended_at TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_silence_rule_scene ON silence_rule(scope, scene_path);
"""


__all__ = [
    "SCHEMA_VERSION",
    "get_db_path",
    "get_connection",
    "get_passive_connection",
    "init_db",
]
