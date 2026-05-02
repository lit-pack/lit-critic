"""Tests for GET /api/inputs/staleness.

Contract tests verifying the rewired route uses ``scene_status_service``
and ``index_status_service`` as its single source of truth.

Cases
-----
1. Clean project — nothing stale
2. One stale scene (extraction_due)
3. One stale CANON index (affects_knowledge = True)
4. Both stale scene + index
5. No DB connection (passive returns None)
6. Regression: stale scene at startup with empty knowledge DB
7. Stale scene with affected session (hash mismatch)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.services.index_status_service import IndexStatus, IndexStatusRecord
from orchestrator.services.scene_status_service import SceneStatus, SceneStatusRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scene_rec(
    scene_key: str,
    status: SceneStatus,
    *,
    current_hash: str = "h1",
    locked: bool = False,
) -> SceneStatusRecord:
    return SceneStatusRecord(
        scene_key=scene_key,
        status=status,
        locked=locked,
        current_hash=current_hash,
        last_extracted_hash=current_hash if status != SceneStatus.extraction_due else None,
        last_analyzed_hash=current_hash if status == SceneStatus.analyzed else None,
        failed_at=None,
    )


def _index_rec(
    name: str,
    status: IndexStatus,
    *,
    affects_knowledge: bool = False,
) -> IndexStatusRecord:
    return IndexStatusRecord(
        index_name=name,
        status=status,
        affects_knowledge=affects_knowledge,
        current_hash="ih1" if status != IndexStatus.absent else None,
        stored_hash="ih1" if status == IndexStatus.current else None,
    )


# Patch targets — always where the name is *imported*, not where it's defined.
_M = "api.routes_management"


@pytest.fixture
def staleness_mocks():
    """Patch every service-level dependency that ``_staleness_from_status`` calls.

    Yields a dict of mock references keyed by a short name.  Default
    return values represent a clean project (no stale inputs, no sessions,
    no orphans).
    """
    with (
        patch(f"{_M}.get_passive_connection") as m_conn,
        patch(f"{_M}.list_scene_statuses") as m_scenes,
        patch(f"{_M}.list_index_statuses") as m_indexes,
        patch(f"{_M}._knowledge_affected_by_scene") as m_ka,
        patch(f"{_M}.detect_orphaned_scene_data") as m_orphans,
        patch(
            "orchestrator.persistence.session_store.SessionStore.list_all"
        ) as m_sess,
    ):
        m_conn.return_value = MagicMock()  # non-None → route enters _staleness_from_status
        m_scenes.return_value = []
        m_indexes.return_value = []
        m_ka.return_value = []
        m_sess.return_value = []
        m_orphans.return_value = {"orphaned_scenes": []}
        yield {
            "conn": m_conn,
            "scenes": m_scenes,
            "indexes": m_indexes,
            "knowledge_affected": m_ka,
            "orphans": m_orphans,
            "sessions": m_sess,
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInputsStaleness:
    """Contract tests for GET /api/inputs/staleness."""

    def test_clean_project(self, client, tmp_path, staleness_mocks):
        """All scenes analyzed, indexes current → empty stale_inputs."""
        staleness_mocks["scenes"].return_value = [
            _scene_rec("chapter01.md", SceneStatus.analyzed),
        ]
        staleness_mocks["indexes"].return_value = [
            _index_rec("CANON.md", IndexStatus.current, affects_knowledge=True),
            _index_rec("STYLE.md", IndexStatus.current),
        ]

        resp = client.get(
            "/api/inputs/staleness", params={"project_path": str(tmp_path)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["stale_inputs"] == []
        assert data["orphaned_scenes"] == []

    def test_one_stale_scene(self, client, tmp_path, staleness_mocks):
        """extraction_due scene → type='scene' in stale_inputs."""
        scene = tmp_path / "chapter01.md"
        scene.write_text("Once upon a time.", encoding="utf-8")

        staleness_mocks["scenes"].return_value = [
            _scene_rec("chapter01.md", SceneStatus.extraction_due, current_hash="new"),
        ]
        staleness_mocks["indexes"].return_value = [
            _index_rec("CANON.md", IndexStatus.current, affects_knowledge=True),
        ]
        staleness_mocks["knowledge_affected"].return_value = ["characters", "glossary"]

        resp = client.get(
            "/api/inputs/staleness", params={"project_path": str(tmp_path)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["stale_inputs"]) == 1
        entry = data["stale_inputs"][0]
        assert entry["type"] == "scene"
        assert entry["path"] == str(scene)
        assert entry["affected_knowledge"] == ["characters", "glossary"]

    def test_one_stale_canon(self, client, tmp_path, staleness_mocks):
        """Stale CANON.md → type='reference', affected_knowledge='all'."""
        staleness_mocks["scenes"].return_value = []
        staleness_mocks["indexes"].return_value = [
            _index_rec("CANON.md", IndexStatus.stale, affects_knowledge=True),
            _index_rec("STYLE.md", IndexStatus.current),
        ]

        resp = client.get(
            "/api/inputs/staleness", params={"project_path": str(tmp_path)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["stale_inputs"]) == 1
        entry = data["stale_inputs"][0]
        assert entry["type"] == "reference"
        assert entry["path"] == str(tmp_path / "CANON.md")
        assert entry["affected_knowledge"] == "all"

    def test_stale_scene_and_index(self, client, tmp_path, staleness_mocks):
        """Both stale scene + stale CANON → two entries of different types."""
        scene = tmp_path / "chapter02.md"
        scene.write_text("Chapter two.", encoding="utf-8")

        staleness_mocks["scenes"].return_value = [
            _scene_rec("chapter02.md", SceneStatus.extraction_due, current_hash="new"),
        ]
        staleness_mocks["indexes"].return_value = [
            _index_rec("CANON.md", IndexStatus.stale, affects_knowledge=True),
            _index_rec("STYLE.md", IndexStatus.current),
        ]

        resp = client.get(
            "/api/inputs/staleness", params={"project_path": str(tmp_path)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["stale_inputs"]) == 2
        types = {e["type"] for e in data["stale_inputs"]}
        assert types == {"reference", "scene"}

    def test_no_db_returns_empty(self, client, tmp_path, staleness_mocks):
        """Passive connection returns None → stale_inputs=[] without error."""
        staleness_mocks["conn"].return_value = None

        resp = client.get(
            "/api/inputs/staleness", params={"project_path": str(tmp_path)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["stale_inputs"] == []

    def test_regression_stale_at_startup_empty_knowledge(
        self, client, tmp_path, staleness_mocks
    ):
        """Regression: fresh DB, one scene stale, empty knowledge DB.

        The exact scenario from the bug report: first run, scene file on
        disk has never been extracted, knowledge DB has no sessions and no
        extracted entities. The endpoint must still report the scene.
        """
        scene = tmp_path / "prologue.md"
        scene.write_text("The story begins.", encoding="utf-8")

        staleness_mocks["scenes"].return_value = [
            _scene_rec("prologue.md", SceneStatus.extraction_due, current_hash="fresh"),
        ]
        staleness_mocks["indexes"].return_value = [
            _index_rec("CANON.md", IndexStatus.absent, affects_knowledge=True),
            _index_rec("STYLE.md", IndexStatus.absent),
        ]
        staleness_mocks["knowledge_affected"].return_value = []
        staleness_mocks["sessions"].return_value = []

        resp = client.get(
            "/api/inputs/staleness", params={"project_path": str(tmp_path)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["stale_inputs"]) == 1
        entry = data["stale_inputs"][0]
        assert entry["type"] == "scene"
        assert entry["path"] == str(scene)
        assert entry["affected_knowledge"] == []
        assert entry["affected_sessions"] == []

    def test_stale_scene_with_affected_session(
        self, client, tmp_path, staleness_mocks
    ):
        """Stale scene with a session whose scene_hash differs → affected_sessions populated."""
        scene = tmp_path / "chapter01.md"
        scene.write_text("Updated content.", encoding="utf-8")

        staleness_mocks["scenes"].return_value = [
            _scene_rec("chapter01.md", SceneStatus.extraction_due, current_hash="new"),
        ]
        staleness_mocks["indexes"].return_value = []
        staleness_mocks["knowledge_affected"].return_value = []
        staleness_mocks["sessions"].return_value = [
            {
                "id": 42,
                "scene_paths": ["chapter01.md"],
                "scene_hash": "old_hash_not_match",
            },
            {
                "id": 99,
                "scene_paths": ["chapter02.md"],  # different scene
                "scene_hash": "irrelevant",
            },
        ]

        resp = client.get(
            "/api/inputs/staleness", params={"project_path": str(tmp_path)}
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["stale_inputs"]) == 1
        entry = data["stale_inputs"][0]
        # Session 42 has the scene with a different hash → affected.
        # Session 99 references a different scene → not affected.
        assert entry["affected_sessions"] == [42]
