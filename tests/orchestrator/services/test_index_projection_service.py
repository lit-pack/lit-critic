from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from orchestrator.persistence import IndexProjectionStore
from orchestrator.persistence.database import get_connection, get_db_path
from orchestrator.services.index_projection_service import (
    get_stale_indexes,
    list_index_projections,
    parse_index_entries,
    refresh_all_indexes,
)


@pytest.mark.parametrize(
    ("index_name", "expected_scope"),
    [
        ("CANON.md", "canon"),
        ("cast", "cast"),
        ("glossary", "glossary"),
        ("threads", "threads"),
        ("timeline", "timeline"),
    ],
)
def test_parse_index_entries_for_each_supported_index_type(index_name: str, expected_scope: str):
    content = """# Header

## Main Section

### Sample Entry <!-- marker -->
Body
"""

    entries = parse_index_entries(index_name, content)

    assert isinstance(entries, list)
    assert len(entries) == 1
    assert entries[0]["scope"] == expected_scope
    assert entries[0]["entry"] == "Sample Entry"
    assert entries[0]["source_file"] == index_name
    assert entries[0]["source_section"] == "Main Section"


def test_parse_index_entries_returns_none_for_style_md():
    assert parse_index_entries("STYLE.md", "# STYLE\n\nFreeform guidance") is None


def test_refresh_all_indexes_is_idempotent_and_keeps_style_hash_only(tmp_path: Path):
    (tmp_path / "CANON.md").write_text("# CANON\n\n## Main\n\n### Alice\nRole", encoding="utf-8")
    (tmp_path / "STYLE.md").write_text("# STYLE\n\nUse short sentences.", encoding="utf-8")

    conn = get_connection(tmp_path)
    try:
        first = refresh_all_indexes(tmp_path, conn)
        second = refresh_all_indexes(tmp_path, conn)

        assert {item["index_name"] for item in first} == {"CANON.md", "STYLE.md"}
        assert all(item["updated"] is True for item in first)
        assert all(item["updated"] is False for item in second)

        style_row = IndexProjectionStore.load_by_name(conn, "STYLE.md")
        assert style_row is not None
        assert style_row["entries_json"] is None
        assert style_row["raw_content_hash"] == style_row["file_hash"]
    finally:
        conn.close()


def test_get_stale_indexes_detects_changed_and_missing_files(tmp_path: Path):
    (tmp_path / "CANON.md").write_text("# CANON\n\n## Main\n\n### Alice\nRole", encoding="utf-8")
    (tmp_path / "STYLE.md").write_text("# STYLE\n\nUse short sentences.", encoding="utf-8")

    conn = get_connection(tmp_path)
    try:
        refresh_all_indexes(tmp_path, conn)
    finally:
        conn.close()

    (tmp_path / "CANON.md").write_text("# CANON\n\n## Main\n\n### Alice\nUpdated", encoding="utf-8")
    (tmp_path / "STYLE.md").unlink()

    stale = get_stale_indexes(tmp_path)
    assert stale == ["CANON.md", "STYLE.md"]


def test_refresh_all_indexes_discovers_fixture_index_files(real_novel_dir: Path, tmp_path: Path):
    shutil.copy2(real_novel_dir / "CANON.md", tmp_path / "CANON.md")

    conn = get_connection(tmp_path)
    try:
        refresh_result = refresh_all_indexes(tmp_path, conn)
    finally:
        conn.close()

    expected_keys = ["CANON.md"]
    assert sorted(item["index_name"] for item in refresh_result) == expected_keys

    listed = list_index_projections(tmp_path)
    assert sorted(item["index_name"] for item in listed) == expected_keys


def test_list_index_projections_returns_empty_without_creating_db(tmp_path: Path):
    db_path = get_db_path(tmp_path)

    listed = list_index_projections(tmp_path)

    assert listed == []
    assert not db_path.exists()
