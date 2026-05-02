"""Tests for orchestrator.services.scene_status_service.

Table-driven tests covering every status derivation path:
  - scene missing on disk
  - no extraction metadata (never extracted)
  - extraction hash mismatch (file edited since extraction)
  - extraction fresh + no snapshot → extracted
  - extraction fresh + snapshot hash mismatch → extracted
  - extraction fresh + snapshot hash match → analyzed
  - extract_status='failed' within backoff → failed
  - extract_status='failed' past backoff → extraction_due
  - locked flag propagation
  - list_scene_statuses with empty project
  - describe_status_reason for every status variant
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator.services.scene_status_service import (
    FAILURE_BACKOFF_SECONDS,
    SceneStatus,
    SceneStatusRecord,
    describe_status_reason,
    list_analyzable_scenes,
    list_scene_statuses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCENE_KEY = "text/chapter01.txt"
HASH_A = "aaa111"
HASH_B = "bbb222"


def _insert_extraction_metadata(
    conn: sqlite3.Connection,
    *,
    scene_filename: str = SCENE_KEY,
    content_hash: str = HASH_A,
    extract_status: str = "ok",
    extraction_locked: int = 0,
    extracted_at: str | None = None,
) -> None:
    """Insert a row into extracted_scene_metadata."""
    if extracted_at is None:
        extracted_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO extracted_scene_metadata
            (scene_filename, content_hash, extracted_at, extract_status, extraction_locked)
        VALUES (?, ?, ?, ?, ?)
        """,
        (scene_filename, content_hash, extracted_at, extract_status, extraction_locked),
    )
    conn.commit()


def _insert_snapshot(
    conn: sqlite3.Connection,
    *,
    scene_paths_json: str = '["text/chapter01.txt"]',
    source_file_hash: str = HASH_A,
    created_at: str | None = None,
) -> None:
    """Insert a row into analysis_snapshot."""
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO analysis_snapshot
            (scene_paths, source_file_hash, created_at)
        VALUES (?, ?, ?)
        """,
        (scene_paths_json, source_file_hash, created_at),
    )
    conn.commit()


def _mock_discover(scene_keys: list[str]):
    """Return a patch that makes discover_scene_relative_paths return *scene_keys*."""
    return patch(
        "orchestrator.services.scene_status_service.discover_scene_relative_paths",
        return_value=scene_keys,
    )


def _mock_hash(mapping: dict[str, str | None]):
    """Return a patch that makes compute_file_hash return from *mapping*.

    If the value is ``None``, raises ``FileNotFoundError`` (simulating a
    missing file on disk).
    """
    def _fake_hash(path: Path) -> str:
        key = path.as_posix()
        # Try matching by the full path or just the scene_key suffix
        for k, v in mapping.items():
            if key.endswith(k):
                if v is None:
                    raise FileNotFoundError(f"No such file: {path}")
                return v
        raise FileNotFoundError(f"Unmapped path: {path}")

    return patch(
        "orchestrator.services.scene_status_service.compute_file_hash",
        side_effect=_fake_hash,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListSceneStatuses:
    """Tests for list_scene_statuses — the primary public entry point."""

    def test_empty_project(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """No scenes discovered → empty list."""
        with _mock_discover([]):
            result = list_scene_statuses(tmp_path, db_conn)
        assert result == []

    def test_scene_missing_on_disk(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """Scene discovered but file hash raises FileNotFoundError → extraction_due."""
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: None}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.status == SceneStatus.extraction_due
        assert rec.current_hash is None

    def test_never_extracted(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """Scene file exists, no extraction metadata → extraction_due."""
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.status == SceneStatus.extraction_due
        assert rec.current_hash == HASH_A
        assert rec.last_extracted_hash is None

    def test_hash_mismatch_extraction_stale(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """File edited since extraction (hash mismatch) → extraction_due."""
        _insert_extraction_metadata(db_conn, content_hash=HASH_A)
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_B}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.status == SceneStatus.extraction_due
        assert rec.current_hash == HASH_B
        assert rec.last_extracted_hash == HASH_A

    def test_extraction_fresh_no_snapshot(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """Extraction hash matches, no analysis snapshot → extracted (manual analysis pending)."""
        _insert_extraction_metadata(db_conn, content_hash=HASH_A)
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.status == SceneStatus.extracted
        assert rec.last_analyzed_hash is None

    def test_extraction_fresh_snapshot_hash_mismatch(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """Extraction fresh, snapshot exists but with old hash → extracted (stale snapshot)."""
        _insert_extraction_metadata(db_conn, content_hash=HASH_A)
        _insert_snapshot(db_conn, source_file_hash=HASH_B)
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.status == SceneStatus.extracted
        assert rec.last_analyzed_hash == HASH_B

    def test_fully_analyzed(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """Extraction fresh + snapshot hash matches current → analyzed."""
        _insert_extraction_metadata(db_conn, content_hash=HASH_A)
        _insert_snapshot(db_conn, source_file_hash=HASH_A)
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.status == SceneStatus.analyzed
        assert rec.current_hash == HASH_A
        assert rec.last_extracted_hash == HASH_A
        assert rec.last_analyzed_hash == HASH_A

    def test_failed_within_backoff(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """extract_status='failed' with recent timestamp → failed status."""
        recent = datetime.now(timezone.utc).isoformat()
        _insert_extraction_metadata(
            db_conn,
            content_hash=HASH_A,
            extract_status="failed",
            extracted_at=recent,
        )
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.status == SceneStatus.failed
        assert rec.failed_at == recent

    def test_failed_past_backoff(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """extract_status='failed' with old timestamp → extraction_due (retry eligible)."""
        old = (datetime.now(timezone.utc) - timedelta(seconds=FAILURE_BACKOFF_SECONDS + 60)).isoformat()
        _insert_extraction_metadata(
            db_conn,
            content_hash=HASH_A,
            extract_status="failed",
            extracted_at=old,
        )
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.status == SceneStatus.extraction_due
        assert rec.failed_at == old

    def test_locked_flag_propagated(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """extraction_locked=1 in metadata → record.locked is True."""
        _insert_extraction_metadata(db_conn, content_hash=HASH_A, extraction_locked=1)
        _insert_snapshot(db_conn, source_file_hash=HASH_A)
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.locked is True
        assert rec.status == SceneStatus.analyzed

    def test_unlocked_by_default(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """No lock flag → record.locked is False."""
        _insert_extraction_metadata(db_conn, content_hash=HASH_A)
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            [rec] = list_scene_statuses(tmp_path, db_conn)
        assert rec.locked is False

    def test_multiple_scenes(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """Multiple scenes return independent status records."""
        scene_a = "text/chapter01.txt"
        scene_b = "text/chapter02.txt"
        _insert_extraction_metadata(db_conn, scene_filename=scene_a, content_hash=HASH_A)
        # chapter02 has no metadata → extraction_due
        with (
            _mock_discover([scene_a, scene_b]),
            _mock_hash({scene_a: HASH_A, scene_b: HASH_B}),
        ):
            results = list_scene_statuses(tmp_path, db_conn)
        assert len(results) == 2
        by_key = {r.scene_key: r for r in results}
        assert by_key[scene_a].status == SceneStatus.extracted
        assert by_key[scene_b].status == SceneStatus.extraction_due


class TestDescribeStatusReason:
    """Tests for describe_status_reason — human-readable explanations."""

    def test_file_missing(self) -> None:
        rec = SceneStatusRecord(
            scene_key=SCENE_KEY, status=SceneStatus.extraction_due,
            locked=False, current_hash=None,
            last_extracted_hash=None, last_analyzed_hash=None, failed_at=None,
        )
        reason = describe_status_reason(rec)
        assert "file missing" in reason

    def test_never_extracted(self) -> None:
        rec = SceneStatusRecord(
            scene_key=SCENE_KEY, status=SceneStatus.extraction_due,
            locked=False, current_hash=HASH_A,
            last_extracted_hash=None, last_analyzed_hash=None, failed_at=None,
        )
        reason = describe_status_reason(rec)
        assert "never extracted" in reason

    def test_extraction_due_hash_mismatch(self) -> None:
        rec = SceneStatusRecord(
            scene_key=SCENE_KEY, status=SceneStatus.extraction_due,
            locked=False, current_hash=HASH_B,
            last_extracted_hash=HASH_A, last_analyzed_hash=None, failed_at=None,
        )
        reason = describe_status_reason(rec)
        assert "edited since last extraction" in reason

    def test_extracted_no_snapshot(self) -> None:
        rec = SceneStatusRecord(
            scene_key=SCENE_KEY, status=SceneStatus.extracted,
            locked=False, current_hash=HASH_A,
            last_extracted_hash=HASH_A, last_analyzed_hash=None, failed_at=None,
        )
        reason = describe_status_reason(rec)
        assert "no analysis snapshot yet" in reason

    def test_analyzed_up_to_date(self) -> None:
        rec = SceneStatusRecord(
            scene_key=SCENE_KEY, status=SceneStatus.analyzed,
            locked=False, current_hash=HASH_A,
            last_extracted_hash=HASH_A, last_analyzed_hash=HASH_A, failed_at=None,
        )
        reason = describe_status_reason(rec)
        assert "up to date" in reason

    def test_failed_with_timestamp(self) -> None:
        ts = "2026-04-17T12:00:00+00:00"
        rec = SceneStatusRecord(
            scene_key=SCENE_KEY, status=SceneStatus.failed,
            locked=False, current_hash=HASH_A,
            last_extracted_hash=HASH_A, last_analyzed_hash=None, failed_at=ts,
        )
        reason = describe_status_reason(rec)
        assert "failed at" in reason
        assert ts in reason


class TestListAnalyzableScenes:
    """Tests for list_analyzable_scenes."""

    def test_empty_project_returns_empty_list(
        self, db_conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """No scenes discovered → empty list."""
        with _mock_discover([]):
            result = list_analyzable_scenes(tmp_path, db_conn)
        assert result == []

    def test_analyzed_scene_excluded(
        self, db_conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Scene with status ``analyzed`` is NOT returned."""
        _insert_extraction_metadata(db_conn, content_hash=HASH_A)
        _insert_snapshot(db_conn, source_file_hash=HASH_A)
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            result = list_analyzable_scenes(tmp_path, db_conn)
        assert result == []

    def test_failed_scene_excluded(
        self, db_conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Scene with status ``failed`` (within backoff) is NOT returned."""
        recent = datetime.now(timezone.utc).isoformat()
        _insert_extraction_metadata(
            db_conn,
            content_hash=HASH_A,
            extract_status="failed",
            extracted_at=recent,
        )
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            result = list_analyzable_scenes(tmp_path, db_conn)
        assert result == []

    def test_extracted_scene_included(
        self, db_conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Scene with status ``extracted`` IS returned."""
        _insert_extraction_metadata(db_conn, content_hash=HASH_A)
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            result = list_analyzable_scenes(tmp_path, db_conn)
        assert len(result) == 1
        entry = result[0]
        assert entry["scene_key"] == SCENE_KEY
        assert entry["status"] == "extracted"
        assert entry["path"].endswith(SCENE_KEY.replace("/", str(Path("/"))))

    def test_extraction_due_scene_included(
        self, db_conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Scene with status ``extraction_due`` IS returned."""
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            result = list_analyzable_scenes(tmp_path, db_conn)
        assert len(result) == 1
        assert result[0]["scene_key"] == SCENE_KEY
        assert result[0]["status"] == "extraction_due"

    def test_mixed_statuses_only_analyzable_returned(
        self, db_conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Only extraction_due and extracted scenes are returned; analyzed is excluded."""
        scene_analyzed = "text/ch01.txt"
        scene_extracted = "text/ch02.txt"
        scene_due = "text/ch03.txt"

        # ch01: analyzed (extraction fresh + matching snapshot)
        _insert_extraction_metadata(db_conn, scene_filename=scene_analyzed, content_hash=HASH_A)
        _insert_snapshot(
            db_conn,
            scene_paths_json=f'["{scene_analyzed}"]',
            source_file_hash=HASH_A,
        )
        # ch02: extracted (no snapshot)
        _insert_extraction_metadata(db_conn, scene_filename=scene_extracted, content_hash=HASH_A)
        # ch03: extraction_due (no metadata)

        hash_map = {scene_analyzed: HASH_A, scene_extracted: HASH_A, scene_due: HASH_B}
        with (
            _mock_discover([scene_analyzed, scene_extracted, scene_due]),
            _mock_hash(hash_map),
        ):
            result = list_analyzable_scenes(tmp_path, db_conn)

        returned_keys = {r["scene_key"] for r in result}
        assert scene_analyzed not in returned_keys
        assert scene_extracted in returned_keys
        assert scene_due in returned_keys

    def test_path_is_absolute(
        self, db_conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        """Each entry's ``path`` field must be absolute (start with the project root)."""
        _insert_extraction_metadata(db_conn, content_hash=HASH_A)
        with _mock_discover([SCENE_KEY]), _mock_hash({SCENE_KEY: HASH_A}):
            result = list_analyzable_scenes(tmp_path, db_conn)
        assert len(result) == 1
        assert result[0]["path"].startswith(str(tmp_path))
