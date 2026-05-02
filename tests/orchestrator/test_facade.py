"""Tests for PlatformFacade orchestration helpers."""

from pathlib import Path

from orchestrator.facade import PlatformFacade
from orchestrator.persistence import ExtractionStore
from orchestrator.persistence.database import get_connection


class _FakeCoreClient:
    def __init__(self):
        self.last_analyze = None

    def analyze(self, req):
        self.last_analyze = req
        return {"ok": True}


def test_load_indexes_from_project_reads_expected_files(tmp_path: Path):
    (tmp_path / "CANON.md").write_text("canon", encoding="utf-8")

    conn = get_connection(tmp_path)
    try:
        ExtractionStore.upsert_character(
            conn,
            name="Basil Hallward",
            category="ally",
            first_seen="chapter-01.txt",
        )
    finally:
        conn.close()

    indexes = PlatformFacade.load_indexes_from_project(tmp_path)

    assert indexes.CANON == "canon"
    assert indexes.CAST is not None
    assert "Basil Hallward" in indexes.CAST
    assert indexes.GLOSSARY == "## Terms\n\n[none]"


def test_load_scene_text_reads_file(tmp_path: Path):
    scene = tmp_path / "scene.md"
    scene.write_text("Once upon a test.", encoding="utf-8")

    loaded = PlatformFacade.load_scene_text(scene)

    assert loaded == "Once upon a test."


def test_load_legacy_indexes_from_project_uses_md_keys_and_optional_files(tmp_path: Path):
    (tmp_path / "CANON.md").write_text("canon", encoding="utf-8")
    (tmp_path / "LEARNING.md").write_text("learned", encoding="utf-8")
    (tmp_path / "TEMPLATE.md").write_text("template", encoding="utf-8")

    indexes = PlatformFacade.load_legacy_indexes_from_project(
        tmp_path,
        optional_filenames=("LEARNING.md", "TEMPLATE.md", "MISSING.md"),
    )

    assert indexes["CANON.md"] == "canon"
    assert indexes["cast"] == ""
    assert indexes["LEARNING.md"] == "learned"
    assert indexes["TEMPLATE.md"] == "template"
    assert "MISSING.md" not in indexes


