"""Tests for orchestrator.services.index_status_service.

Table-driven tests covering every status derivation path:
  - index file current (hash match) for CANON.md / STYLE.md
  - index file stale (hash mismatch)
  - index file stale (never projected — no DB row)
  - index file absent (file does not exist on disk)
  - affects_knowledge flag: CANON.md = True, STYLE.md = False
  - describe_status_reason for every status variant
  - get_index_status single-index helper
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator.services.index_status_service import (
    IndexStatus,
    IndexStatusRecord,
    describe_status_reason,
    get_index_status,
    list_index_statuses,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HASH_A = "aaa111"
HASH_B = "bbb222"


def _insert_index_projection(
    conn: sqlite3.Connection,
    *,
    index_name: str = "CANON.md",
    file_hash: str = HASH_A,
) -> None:
    """Insert a row into index_projection."""
    conn.execute(
        """
        INSERT INTO index_projection
            (index_name, file_hash, entries_json, raw_content_hash, last_refreshed_at)
        VALUES (?, ?, '[]', ?, '2026-01-01T00:00:00')
        """,
        (index_name, file_hash, file_hash),
    )
    conn.commit()


def _mock_file_exists(existing: set[str]):
    """Patch Path.exists so that only files whose name is in *existing* return True.

    Delegates to the real ``Path.exists`` for non-index paths so that
    pytest / tmp_path infrastructure is not broken.
    """
    _real_exists = Path.exists

    def _fake_exists(self: Path) -> bool:
        if self.name in ("CANON.md", "STYLE.md"):
            return self.name in existing
        return _real_exists(self)

    return patch.object(Path, "exists", _fake_exists)


def _mock_hash(mapping: dict[str, str]):
    """Patch compute_file_hash to return values from *mapping* keyed by filename."""

    def _fake_hash(path: Path) -> str:
        name = path.name
        if name in mapping:
            return mapping[name]
        raise FileNotFoundError(f"Unmapped path: {path}")

    return patch(
        "orchestrator.services.index_status_service.compute_file_hash",
        side_effect=_fake_hash,
    )


# ---------------------------------------------------------------------------
# Tests — list_index_statuses
# ---------------------------------------------------------------------------


class TestListIndexStatuses:
    """Tests for list_index_statuses — the primary public entry point."""

    def test_both_current(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """Both index files exist and match stored hashes → current."""
        _insert_index_projection(db_conn, index_name="CANON.md", file_hash=HASH_A)
        _insert_index_projection(db_conn, index_name="STYLE.md", file_hash=HASH_B)
        with (
            _mock_file_exists({"CANON.md", "STYLE.md"}),
            _mock_hash({"CANON.md": HASH_A, "STYLE.md": HASH_B}),
        ):
            results = list_index_statuses(tmp_path, db_conn)
        by_name = {r.index_name: r for r in results}
        assert by_name["CANON.md"].status == IndexStatus.current
        assert by_name["STYLE.md"].status == IndexStatus.current

    def test_canon_stale_hash_mismatch(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """CANON.md file hash differs from stored → stale."""
        _insert_index_projection(db_conn, index_name="CANON.md", file_hash=HASH_A)
        with (
            _mock_file_exists({"CANON.md", "STYLE.md"}),
            _mock_hash({"CANON.md": HASH_B, "STYLE.md": HASH_A}),
        ):
            results = list_index_statuses(tmp_path, db_conn)
        by_name = {r.index_name: r for r in results}
        assert by_name["CANON.md"].status == IndexStatus.stale
        assert by_name["CANON.md"].current_hash == HASH_B
        assert by_name["CANON.md"].stored_hash == HASH_A

    def test_never_projected(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """Index file exists but no DB row → stale (never projected)."""
        with (
            _mock_file_exists({"CANON.md"}),
            _mock_hash({"CANON.md": HASH_A}),
        ):
            results = list_index_statuses(tmp_path, db_conn)
        by_name = {r.index_name: r for r in results}
        assert by_name["CANON.md"].status == IndexStatus.stale
        assert by_name["CANON.md"].stored_hash is None
        assert by_name["CANON.md"].current_hash == HASH_A

    def test_absent_file(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """Index file does not exist on disk → absent."""
        with _mock_file_exists(set()):
            results = list_index_statuses(tmp_path, db_conn)
        by_name = {r.index_name: r for r in results}
        assert by_name["CANON.md"].status == IndexStatus.absent
        assert by_name["CANON.md"].current_hash is None
        assert by_name["STYLE.md"].status == IndexStatus.absent

    def test_affects_knowledge_canon(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """CANON.md has affects_knowledge=True."""
        _insert_index_projection(db_conn, index_name="CANON.md", file_hash=HASH_A)
        with (
            _mock_file_exists({"CANON.md"}),
            _mock_hash({"CANON.md": HASH_A}),
        ):
            results = list_index_statuses(tmp_path, db_conn)
        by_name = {r.index_name: r for r in results}
        assert by_name["CANON.md"].affects_knowledge is True

    def test_affects_knowledge_style(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """STYLE.md has affects_knowledge=False."""
        _insert_index_projection(db_conn, index_name="STYLE.md", file_hash=HASH_A)
        with (
            _mock_file_exists({"STYLE.md"}),
            _mock_hash({"STYLE.md": HASH_A}),
        ):
            results = list_index_statuses(tmp_path, db_conn)
        by_name = {r.index_name: r for r in results}
        assert by_name["STYLE.md"].affects_knowledge is False

    def test_mixed_statuses(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        """CANON current, STYLE absent → mixed statuses in one call."""
        _insert_index_projection(db_conn, index_name="CANON.md", file_hash=HASH_A)
        with (
            _mock_file_exists({"CANON.md"}),
            _mock_hash({"CANON.md": HASH_A}),
        ):
            results = list_index_statuses(tmp_path, db_conn)
        by_name = {r.index_name: r for r in results}
        assert by_name["CANON.md"].status == IndexStatus.current
        assert by_name["STYLE.md"].status == IndexStatus.absent


# ---------------------------------------------------------------------------
# Tests — get_index_status
# ---------------------------------------------------------------------------


class TestGetIndexStatus:
    """Tests for get_index_status — single-index convenience helper."""

    def test_single_current(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        _insert_index_projection(db_conn, index_name="CANON.md", file_hash=HASH_A)
        with (
            _mock_file_exists({"CANON.md"}),
            _mock_hash({"CANON.md": HASH_A}),
        ):
            rec = get_index_status("CANON.md", project_root=tmp_path, conn=db_conn)
        assert rec.status == IndexStatus.current
        assert rec.affects_knowledge is True

    def test_single_absent(self, db_conn: sqlite3.Connection, tmp_path: Path) -> None:
        with _mock_file_exists(set()):
            rec = get_index_status("STYLE.md", project_root=tmp_path, conn=db_conn)
        assert rec.status == IndexStatus.absent
        assert rec.affects_knowledge is False


# ---------------------------------------------------------------------------
# Tests — describe_status_reason
# ---------------------------------------------------------------------------


class TestDescribeStatusReason:
    """Tests for describe_status_reason — human-readable explanations."""

    def test_current(self) -> None:
        rec = IndexStatusRecord(
            index_name="CANON.md", status=IndexStatus.current,
            affects_knowledge=True, current_hash=HASH_A, stored_hash=HASH_A,
        )
        assert "up to date" in describe_status_reason(rec)

    def test_stale_never_projected(self) -> None:
        rec = IndexStatusRecord(
            index_name="CANON.md", status=IndexStatus.stale,
            affects_knowledge=True, current_hash=HASH_A, stored_hash=None,
        )
        reason = describe_status_reason(rec)
        assert "never projected" in reason

    def test_stale_hash_mismatch(self) -> None:
        rec = IndexStatusRecord(
            index_name="STYLE.md", status=IndexStatus.stale,
            affects_knowledge=False, current_hash=HASH_B, stored_hash=HASH_A,
        )
        reason = describe_status_reason(rec)
        assert "edited since last projection" in reason
        assert HASH_B in reason
        assert HASH_A in reason

    def test_absent(self) -> None:
        rec = IndexStatusRecord(
            index_name="CANON.md", status=IndexStatus.absent,
            affects_knowledge=True, current_hash=None, stored_hash=None,
        )
        assert "does not exist" in describe_status_reason(rec)
