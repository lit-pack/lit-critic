import sqlite3

import pytest

from orchestrator.persistence.database import (
    SCHEMA_VERSION,
    get_connection,
    get_db_path,
    get_passive_connection,
    init_db,
)


def test_get_passive_connection_returns_none_without_creating_db(tmp_path):
    db_path = get_db_path(tmp_path)

    conn = get_passive_connection(tmp_path)

    assert conn is None
    assert not db_path.exists()


def test_get_passive_connection_opens_existing_db_without_enabling_wal(tmp_path):
    db_path = get_db_path(tmp_path)

    seeded_conn = sqlite3.connect(str(db_path))
    try:
        init_db(seeded_conn)
        assert seeded_conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    finally:
        seeded_conn.close()

    assert db_path.exists()
    assert not db_path.with_name(f"{db_path.name}-wal").exists()
    assert not db_path.with_name(f"{db_path.name}-shm").exists()

    conn = get_passive_connection(tmp_path)

    assert conn is not None
    try:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only|write"):
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION + 1,),
            )
    finally:
        conn.close()

    assert not db_path.with_name(f"{db_path.name}-wal").exists()
    assert not db_path.with_name(f"{db_path.name}-shm").exists()


def test_get_connection_still_initializes_schema_and_write_pragmas(tmp_path):
    db_path = get_db_path(tmp_path)

    conn = get_connection(tmp_path)

    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert db_path.exists()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == SCHEMA_VERSION
        assert {"schema_version", "analysis_snapshot", "snapshot_finding", "learning_entry"}.issubset(tables)
        assert "session" not in tables
        assert "finding" not in tables
    finally:
        conn.close()
