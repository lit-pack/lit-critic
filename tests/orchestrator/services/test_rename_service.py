"""Tests for scene rename workflow service."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.scene_projection_store import SceneProjectionStore
from orchestrator.persistence.database import get_connection
from orchestrator.services.rename_service import rename_scene


def _write_scene(path: Path, *, prev: str, next_value: str) -> None:
    path.write_text(
        (
            "@@META\n"
            f"Prev: {prev}\n"
            f"Next: {next_value}\n"
            "@@END\n\n"
            "Body\n"
        ),
        encoding="utf-8",
    )


def test_rename_scene_updates_files_and_db_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(tmp_path / "user-config.json"))

    text_dir = tmp_path / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    scene_1 = text_dir / "scene-01.txt"
    scene_2 = text_dir / "scene-02.txt"
    scene_3 = text_dir / "scene-03.txt"

    _write_scene(scene_1, prev="None", next_value="scene-02.txt")
    _write_scene(scene_2, prev="text/scene-01.txt", next_value="text/scene-03.txt")
    _write_scene(scene_3, prev="text/scene-02.txt", next_value="None")

    old_key = "text/scene-02.txt"
    new_key = "text/scene-02-renamed.txt"

    conn = get_connection(tmp_path)
    try:
        SceneProjectionStore.upsert(
            conn,
            scene_path="text/scene-01.txt",
            scene_id=None,
            file_hash="hash-1",
            meta_json={"prev": "None", "next": "scene-02.txt"},
        )
        SceneProjectionStore.upsert(
            conn,
            scene_path=old_key,
            scene_id=None,
            file_hash="hash-2",
            meta_json={"prev": "text/scene-01.txt", "next": "text/scene-03.txt"},
        )
        SceneProjectionStore.upsert(
            conn,
            scene_path="text/scene-03.txt",
            scene_id=None,
            file_hash="hash-3",
            meta_json={"prev": old_key, "next": "None"},
        )

        ExtractionStore.upsert_scene_metadata(conn, scene_filename=old_key, content_hash="scene-hash")
        ExtractionStore.upsert_thread_event(
            conn,
            thread_id="vault-thread",
            scene_filename=old_key,
            event_type="opened",
            notes="event",
        )
        ExtractionStore.upsert_timeline(
            conn,
            scene_filename=old_key,
            summary="summary",
        )

        result = rename_scene(tmp_path, old_key, new_key, conn)

        assert (tmp_path / old_key).exists() is False
        assert (tmp_path / new_key).exists()

        scene_1_content = scene_1.read_text(encoding="utf-8")
        scene_3_content = scene_3.read_text(encoding="utf-8")
        assert "Next: scene-02-renamed.txt" in scene_1_content
        assert "Prev: text/scene-02-renamed.txt" in scene_3_content

        assert SceneProjectionStore.load_by_path(conn, old_key) is None
        assert SceneProjectionStore.load_by_path(conn, new_key) is not None

        scene_1_projection = SceneProjectionStore.load_by_path(conn, "text/scene-01.txt")
        scene_3_projection = SceneProjectionStore.load_by_path(conn, "text/scene-03.txt")
        assert scene_1_projection is not None
        assert scene_3_projection is not None
        assert scene_1_projection["meta_json"]["next"] == "scene-02-renamed.txt"
        assert scene_3_projection["meta_json"]["prev"] == "text/scene-02-renamed.txt"

        assert ExtractionStore.load_scene_metadata(conn, old_key) is None
        assert ExtractionStore.load_scene_metadata(conn, new_key) is not None
        thread_events = ExtractionStore.load_thread_events(conn, "vault-thread")
        assert thread_events[0]["scene_filename"] == new_key
        timeline_rows = ExtractionStore.load_all_timeline(conn)
        assert timeline_rows[0]["scene_filename"] == new_key

        assert result["old_scene"] == old_key
        assert result["new_scene"] == new_key
        assert result["updated_scene_projection_row"] == 1
        assert result["updated_extracted_scene_metadata_row"] == 1
        assert result["updated_extracted_thread_events_rows"] == 1
        assert result["updated_extracted_timeline_row"] == 1
        # session table removed in v22 — expect 0 session rows updated
        assert result["updated_session_rows"] == 0
    finally:
        conn.close()


def test_rename_scene_updates_character_and_term_source_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(tmp_path / "user-config.json"))

    text_dir = tmp_path / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    old_scene = text_dir / "scene-old.txt"
    _write_scene(old_scene, prev="None", next_value="None")

    old_key = "text/scene-old.txt"
    new_key = "text/scene-new.txt"

    conn = get_connection(tmp_path)
    try:
        ExtractionStore.upsert_character(conn, name="Alice")
        ExtractionStore.upsert_character_source(conn, name="Alice", scene_filename=old_key)
        ExtractionStore.upsert_term(conn, term="magic")
        ExtractionStore.upsert_term_source(conn, term="magic", scene_filename=old_key)

        result = rename_scene(tmp_path, old_key, new_key, conn)

        alice_scenes = ExtractionStore.load_character_scenes(conn, "Alice")
        assert alice_scenes == [new_key]
        magic_scenes = ExtractionStore.load_term_scenes(conn, "magic")
        assert magic_scenes == [new_key]

        assert result["updated_character_source_rows"] == 1
        assert result["updated_term_source_rows"] == 1
    finally:
        conn.close()


def test_rename_scene_updates_knowledge_scene_refs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(tmp_path / "user-config.json"))

    text_dir = tmp_path / "text"
    text_dir.mkdir(parents=True, exist_ok=True)

    old_scene = text_dir / "scene-old.txt"
    _write_scene(old_scene, prev="None", next_value="None")

    old_key = "text/scene-old.txt"
    new_key = "text/scene-new.txt"

    conn = get_connection(tmp_path)
    try:
        ExtractionStore.upsert_character(conn, name="Alice", first_seen=old_key)
        ExtractionStore.upsert_term(conn, term="magic", first_seen=old_key)
        ExtractionStore.upsert_thread(
            conn,
            thread_id="t1",
            opened_in=old_key,
            last_advanced=old_key,
            resolved_in=old_key,
        )

        result = rename_scene(tmp_path, old_key, new_key, conn)

        chars = ExtractionStore.load_all_characters(conn)
        assert chars[0]["first_seen"] == new_key

        terms = ExtractionStore.load_all_terms(conn)
        assert terms[0]["first_seen"] == new_key

        threads = ExtractionStore.load_all_threads(conn)
        assert threads[0]["opened_in"] == new_key
        assert threads[0]["last_advanced"] == new_key
        assert threads[0]["resolved_in"] == new_key

        assert result["updated_character_first_seen_rows"] == 1
        assert result["updated_term_first_seen_rows"] == 1
        assert result["updated_thread_opened_rows"] == 1
        assert result["updated_thread_last_advanced_rows"] == 1
        assert result["updated_thread_resolved_rows"] == 1
    finally:
        conn.close()


def test_rename_scene_raises_when_source_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(tmp_path / "user-config.json"))

    conn = get_connection(tmp_path)
    try:
        with pytest.raises(FileNotFoundError):
            rename_scene(tmp_path, "text/missing.txt", "text/new-name.txt", conn)
    finally:
        conn.close()
