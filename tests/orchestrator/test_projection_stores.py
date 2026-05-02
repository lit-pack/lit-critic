import sqlite3

from orchestrator.persistence.database import init_db
from orchestrator.persistence.index_projection_store import IndexProjectionStore
from orchestrator.persistence.scene_projection_store import SceneProjectionStore
def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_scene_projection_store_upsert_load_stale_and_delete():
    conn = _conn()
    try:
        SceneProjectionStore.upsert(
            conn,
            scene_path="text/ch1.txt",
            scene_id="SCN-001",
            file_hash="hash-v1",
            meta_json={"title": "Chapter 1"},
        )

        row = SceneProjectionStore.load_by_path(conn, "text/ch1.txt")
        assert row is not None
        assert row["scene_id"] == "SCN-001"
        assert row["file_hash"] == "hash-v1"
        assert row["meta_json"]["title"] == "Chapter 1"

        all_rows = SceneProjectionStore.load_all(conn)
        assert [r["scene_path"] for r in all_rows] == ["text/ch1.txt"]

        assert SceneProjectionStore.is_stale(conn, "text/ch1.txt", "hash-v1") is False
        assert SceneProjectionStore.is_stale(conn, "text/ch1.txt", "hash-v2") is True
        assert SceneProjectionStore.is_stale(conn, "text/missing.txt", "hash-any") is True

        SceneProjectionStore.upsert(
            conn,
            scene_path="text/ch1.txt",
            scene_id="SCN-001B",
            file_hash="hash-v2",
            meta_json={"title": "Chapter 1 revised"},
        )

        updated = SceneProjectionStore.load_by_path(conn, "text/ch1.txt")
        assert updated is not None
        assert updated["scene_id"] == "SCN-001B"
        assert updated["file_hash"] == "hash-v2"
        assert updated["meta_json"]["title"] == "Chapter 1 revised"

        SceneProjectionStore.delete_by_path(conn, "text/ch1.txt")
        assert SceneProjectionStore.load_by_path(conn, "text/ch1.txt") is None
    finally:
        conn.close()


def test_index_projection_store_upsert_load_and_stale_detection():
    conn = _conn()
    try:
        IndexProjectionStore.upsert(
            conn,
            index_name="cast",
            file_hash="index-hash-v1",
            entries_json=[{"name": "Alice", "role": "lead"}],
        )

        row = IndexProjectionStore.load_by_name(conn, "cast")
        assert row is not None
        assert row["index_name"] == "cast"
        assert row["file_hash"] == "index-hash-v1"
        assert isinstance(row["entries_json"], list)
        assert row["entries_json"][0]["name"] == "Alice"
        assert row["raw_content_hash"] == "index-hash-v1"

        all_rows = IndexProjectionStore.load_all(conn)
        assert [r["index_name"] for r in all_rows] == ["cast"]

        assert IndexProjectionStore.is_stale(conn, "cast", "index-hash-v1") is False
        assert IndexProjectionStore.is_stale(conn, "cast", "index-hash-v2") is True
        assert IndexProjectionStore.is_stale(conn, "threads", "index-hash") is True

        IndexProjectionStore.upsert(
            conn,
            index_name="STYLE.md",
            file_hash="style-hash-v1",
            entries_json=None,
            raw_content_hash="style-raw-hash-v1",
        )

        style_row = IndexProjectionStore.load_by_name(conn, "STYLE.md")
        assert style_row is not None
        assert style_row["entries_json"] is None
        assert style_row["raw_content_hash"] == "style-raw-hash-v1"
    finally:
        conn.close()


