from __future__ import annotations

import json
from pathlib import Path

from orchestrator.persistence import SceneProjectionStore
from orchestrator.persistence.database import get_connection, get_db_path
from orchestrator.services.scene_projection_service import (
    compute_file_hash,
    list_scene_projections,
    parse_scene_meta,
    refresh_all_scenes,
    refresh_scene_projection,
)


def test_parse_scene_meta_extracts_fields_from_meta_block():
    scene_content = """@@META
ID: 01.02.03
POV: Alice
Prev: text/chapter-00.txt
Next: text/chapter-02.txt
THREADS: vault_mystery, blood_oath
NotAField
@@END

Scene body text.
"""

    meta = parse_scene_meta(scene_content)

    assert meta == {
        "prev": "text/chapter-00.txt",
        "next": "text/chapter-02.txt",
    }


def test_compute_file_hash_is_stable_and_changes_on_edit(tmp_path: Path):
    scene_file = tmp_path / "scene.txt"
    scene_file.write_text("Version A", encoding="utf-8")

    hash_a1 = compute_file_hash(scene_file)
    hash_a2 = compute_file_hash(scene_file)

    assert hash_a1 == hash_a2
    assert len(hash_a1) == 16

    scene_file.write_text("Version B", encoding="utf-8")
    hash_b = compute_file_hash(scene_file)

    assert hash_b != hash_a1


def test_refresh_scene_projection_is_idempotent(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "user-config.json"
    config_path.write_text(
        json.dumps({"scene_folder": "text", "scene_extensions": ["txt"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))

    scene_dir = tmp_path / "text"
    scene_dir.mkdir()
    scene_file = scene_dir / "scene-01.txt"
    scene_file.write_text(
        "@@META\nID: 01.01.01\nPOV: Alice\nPrev: text/scene-00.txt\nNext: text/scene-02.txt\n@@END\n\nBody",
        encoding="utf-8",
    )

    conn = get_connection(tmp_path)
    try:
        first = refresh_scene_projection(tmp_path, Path("text/scene-01.txt"), conn)
        second = refresh_scene_projection(tmp_path, Path("text/scene-01.txt"), conn)

        assert first["updated"] is True
        assert second["updated"] is False

        row = SceneProjectionStore.load_by_path(conn, "text/scene-01.txt")
        assert row is not None
        assert row["scene_id"] is None
        assert row["meta_json"] == {
            "prev": "text/scene-00.txt",
            "next": "text/scene-02.txt",
        }

        listed = list_scene_projections(tmp_path)
        assert [item["scene_path"] for item in listed] == ["text/scene-01.txt"]
    finally:
        conn.close()


def test_refresh_all_scenes_discovers_fixture_files(real_novel_dir: Path, monkeypatch, tmp_path: Path):
    config_path = tmp_path / "user-config.json"
    config_path.write_text(
        json.dumps({"scene_folder": ".", "scene_extensions": ["txt"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))

    expected_scene_files = sorted(path.name for path in real_novel_dir.glob("chapter-*.txt"))
    assert expected_scene_files

    conn = get_connection(real_novel_dir)
    try:
        refreshed = refresh_all_scenes(real_novel_dir, conn)

        assert len(refreshed) == len(expected_scene_files)
        assert sorted(item["scene_path"] for item in refreshed) == expected_scene_files

        rows = SceneProjectionStore.load_all(conn)
        assert len(rows) == len(expected_scene_files)
        assert sorted(row["scene_path"] for row in rows) == expected_scene_files
    finally:
        conn.close()


def test_list_scene_projections_returns_empty_without_creating_db(tmp_path: Path):
    db_path = get_db_path(tmp_path)

    listed = list_scene_projections(tmp_path)

    assert listed == []
    assert not db_path.exists()


def test_refresh_all_scenes_returns_empty_when_scene_folder_missing(tmp_path: Path, monkeypatch):
    """When scene_folder is configured but the directory doesn't exist, return empty list.

    The production code no longer falls back to the project root — it logs a warning
    and returns [] so the caller knows no scenes were discovered.
    """
    config_path = tmp_path / "user-config.json"
    config_path.write_text(
        json.dumps({"scene_folder": "text", "scene_extensions": ["txt"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))

    (tmp_path / "chapter-01.txt").write_text("@@META\nID: root-01\n@@END\n", encoding="utf-8")
    (tmp_path / "chapter-02.txt").write_text("@@META\nID: root-02\n@@END\n", encoding="utf-8")

    conn = get_connection(tmp_path)
    try:
        refreshed = refresh_all_scenes(tmp_path, conn)
    finally:
        conn.close()

    # scene_folder 'text' doesn't exist → empty discovery (no fallback to root)
    assert refreshed == []


def test_refresh_all_scenes_prefers_text_folder_when_scene_folder_dot(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "user-config.json"
    config_path.write_text(
        json.dumps({"scene_folder": ".", "scene_extensions": ["txt"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))

    text_dir = tmp_path / "text"
    text_dir.mkdir()
    (text_dir / "chapter-01.txt").write_text("@@META\nID: t-01\n@@END\n", encoding="utf-8")
    (text_dir / "chapter-02.txt").write_text("@@META\nID: t-02\n@@END\n", encoding="utf-8")

    (tmp_path / ".cspell").mkdir()
    (tmp_path / ".cspell" / "custom-dictionary-workspace.txt").write_text("noise", encoding="utf-8")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "amomonaima.txt").write_text("noise", encoding="utf-8")

    conn = get_connection(tmp_path)
    try:
        refreshed = refresh_all_scenes(tmp_path, conn)
    finally:
        conn.close()

    assert sorted(item["scene_path"] for item in refreshed) == [
        "text/chapter-01.txt",
        "text/chapter-02.txt",
    ]


def test_list_scene_projections_filters_out_stale_non_discoverable_rows(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "user-config.json"
    config_path.write_text(
        json.dumps({"scene_folder": "text", "scene_extensions": ["md"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))

    text_dir = tmp_path / "text"
    text_dir.mkdir()
    (text_dir / "chapter-01.md").write_text("@@META\nID: md-01\n@@END\n", encoding="utf-8")

    conn = get_connection(tmp_path)
    try:
        SceneProjectionStore.upsert(
            conn,
            scene_path=".cspell/custom-dictionary-workspace.txt",
            scene_id=None,
            file_hash="noise-1",
            meta_json={},
        )
        SceneProjectionStore.upsert(
            conn,
            scene_path="out/amomonaima.txt",
            scene_id=None,
            file_hash="noise-2",
            meta_json={},
        )
        SceneProjectionStore.upsert(
            conn,
            scene_path="text/chapter-01.md",
            scene_id="md-01",
            file_hash="real-1",
            meta_json={"id": "md-01"},
        )
    finally:
        conn.close()

    listed = list_scene_projections(tmp_path)

    assert [row["scene_path"] for row in listed] == ["text/chapter-01.md"]


def test_refresh_all_scenes_does_not_fallback_to_root_when_configured_folder_exists(
    tmp_path: Path,
    monkeypatch,
):
    config_path = tmp_path / "user-config.json"
    config_path.write_text(
        json.dumps({"scene_folder": "text", "scene_extensions": ["txt"]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))

    text_dir = tmp_path / "text"
    text_dir.mkdir()
    (text_dir / "chapter-01.md").write_text("@@META\nID: md-01\n@@END\n", encoding="utf-8")

    (tmp_path / ".cspell").mkdir()
    (tmp_path / ".cspell" / "custom-dictionary-workspace.txt").write_text("noise", encoding="utf-8")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "amomonaima.txt").write_text("noise", encoding="utf-8")

    conn = get_connection(tmp_path)
    try:
        refreshed = refresh_all_scenes(tmp_path, conn)
    finally:
        conn.close()

    assert refreshed == []
