"""
Tests for management routes (sessions, scenes, indexes, knowledge, analytics, learning).
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from api.routes import analysis_engine
from api.analysis_engine import ResumeScenePathError
from orchestrator.runtime.models import Finding, SessionState, LearningData


class TestManagementEndpoints:
    """Test session and learning management routes (Phase 2)."""

    @patch("api.routes_management.list_scene_projections")
    def test_list_scenes_returns_projection_rows(
        self,
        mock_list_scene_projections,
        client,
        temp_project_dir,
    ):
        """GET /api/scenes should return projected scene rows."""
        mock_list_scene_projections.return_value = [
            {
                "scene_path": "text/chapter-01.txt",
                "scene_id": "scene-01",
                "file_hash": "abc123",
                "meta_json": {"id": "scene-01"},
            }
        ]

        response = client.get(f"/api/scenes?project_path={temp_project_dir}")
        assert response.status_code == 200
        data = response.json()
        assert data["scenes"] == mock_list_scene_projections.return_value
        mock_list_scene_projections.assert_called_once_with(Path(str(temp_project_dir)))

    @patch("api.routes_management.refresh_project_knowledge")
    def test_refresh_scenes_returns_refresh_summary(
        self,
        mock_refresh_project_knowledge,
        client,
        temp_project_dir,
    ):
        """POST /api/scenes/refresh should report totals and updates."""
        mock_refresh_project_knowledge.return_value = {
            "scenes": [{"scene_path": "text/chapter-01.txt", "updated": True}],
            "indexes": [{"index_name": "CANON.md", "updated": False}],
            "scene_total": 1,
            "scene_updated": 1,
            "index_total": 1,
            "index_updated": 0,
        }

        response = client.post(
            "/api/scenes/refresh",
            json={"project_path": str(temp_project_dir)},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deprecated"] is True
        assert data["replacement"] == "/api/knowledge/refresh"
        assert data["scene_total"] == 1
        assert data["index_total"] == 1
        assert data["scenes"] == mock_refresh_project_knowledge.return_value["scenes"]
        assert mock_refresh_project_knowledge.call_count == 1
        assert mock_refresh_project_knowledge.call_args[0][0] == Path(str(temp_project_dir))

    @patch("api.routes_management.ExtractionStore.lock_scene")
    def test_lock_scene_returns_locked_true(
        self,
        mock_lock_scene,
        client,
        temp_project_dir,
    ):
        """POST /api/scenes/lock should lock extraction for one scene."""
        response = client.post(
            "/api/scenes/lock",
            json={
                "project_path": str(temp_project_dir),
                "scene_filename": "text/chapter-01.txt",
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "locked": True,
            "scene_filename": "text/chapter-01.txt",
        }
        mock_lock_scene.assert_called_once()

    @patch("api.routes_management.ExtractionStore.unlock_scene")
    def test_unlock_scene_returns_unlocked_true(
        self,
        mock_unlock_scene,
        client,
        temp_project_dir,
    ):
        """POST /api/scenes/unlock should unlock extraction for one scene."""
        response = client.post(
            "/api/scenes/unlock",
            json={
                "project_path": str(temp_project_dir),
                "scene_filename": "text/chapter-01.txt",
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "unlocked": True,
            "scene_filename": "text/chapter-01.txt",
        }
        mock_unlock_scene.assert_called_once()

    @patch("api.routes_management.rename_scene")
    def test_rename_scene_returns_renamed_payload(
        self,
        mock_rename_scene,
        client,
        temp_project_dir,
    ):
        """POST /api/scenes/rename should return rename summary payload."""
        mock_rename_scene.return_value = {
            "old_scene": "text/chapter-01.txt",
            "new_scene": "text/chapter-01-renamed.txt",
            "updated_scene_files": ["text/chapter-02.txt"],
            "updated_scene_projection_row": 1,
            "updated_scene_projection_meta_rows": 1,
            "updated_extracted_scene_metadata_row": 1,
            "updated_extracted_thread_events_rows": 0,
            "updated_extracted_timeline_row": 0,
            "updated_session_rows": 1,
        }

        response = client.post(
            "/api/scenes/rename",
            json={
                "project_path": str(temp_project_dir),
                "old_filename": "text/chapter-01.txt",
                "new_filename": "text/chapter-01-renamed.txt",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["renamed"] is True
        assert payload["old_scene"] == "text/chapter-01.txt"
        assert payload["new_scene"] == "text/chapter-01-renamed.txt"
        mock_rename_scene.assert_called_once()

    @patch("api.routes_management.rename_scene")
    def test_rename_scene_missing_source_returns_404(
        self,
        mock_rename_scene,
        client,
        temp_project_dir,
    ):
        """POST /api/scenes/rename should map FileNotFoundError to 404."""
        mock_rename_scene.side_effect = FileNotFoundError("Scene file not found")

        response = client.post(
            "/api/scenes/rename",
            json={
                "project_path": str(temp_project_dir),
                "old_filename": "text/missing.txt",
                "new_filename": "text/chapter-01-renamed.txt",
            },
        )

        assert response.status_code == 404
        assert "Scene file not found" in response.json()["detail"]

    @patch("api.routes_management.rename_scene")
    def test_rename_scene_conflict_returns_409(
        self,
        mock_rename_scene,
        client,
        temp_project_dir,
    ):
        """POST /api/scenes/rename should map FileExistsError to 409."""
        mock_rename_scene.side_effect = FileExistsError("Target scene file already exists")

        response = client.post(
            "/api/scenes/rename",
            json={
                "project_path": str(temp_project_dir),
                "old_filename": "text/chapter-01.txt",
                "new_filename": "text/chapter-02.txt",
            },
        )

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    @patch("api.routes_management.compute_file_hash")
    @patch("api.routes_management.list_scene_projections")
    def test_scene_status_reports_projection_freshness(
        self,
        mock_list_scene_projections,
        mock_compute_file_hash,
        client,
        temp_project_dir,
    ):
        """GET /api/scenes/{scene_path}/status should report stale/projected flags."""
        scene_file = temp_project_dir / "text" / "chapter-01.txt"
        scene_file.parent.mkdir(parents=True, exist_ok=True)
        scene_file.write_text("scene content", encoding="utf-8")

        mock_compute_file_hash.return_value = "hash-1"
        mock_list_scene_projections.return_value = [
            {"scene_path": "text/chapter-01.txt", "file_hash": "hash-1"}
        ]

        response = client.get(
            f"/api/scenes/text/chapter-01.txt/status?project_path={temp_project_dir}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data == {
            "scene_path": "text/chapter-01.txt",
            "stale": False,
            "projected": True,
            "file_hash": "hash-1",
            "stored_hash": "hash-1",
        }
        mock_compute_file_hash.assert_called_once_with(scene_file)
        mock_list_scene_projections.assert_called_once_with(Path(str(temp_project_dir)))

    def test_scene_status_nonexistent_scene_404(self, client, temp_project_dir):
        """Scene status endpoint returns 404 when scene file is missing."""
        response = client.get(
            f"/api/scenes/text/missing.txt/status?project_path={temp_project_dir}"
        )
        assert response.status_code == 404

    @patch("api.routes_management.list_index_projections")
    def test_list_indexes_returns_projection_rows(
        self,
        mock_list_index_projections,
        client,
        temp_project_dir,
    ):
        """GET /api/indexes should return projected index rows."""
        mock_list_index_projections.return_value = [
            {
                "index_name": "CANON.md",
                "file_hash": "hash-cast",
                "entries_json": [{"entry": "Aria Vale"}],
            }
        ]

        response = client.get(f"/api/indexes?project_path={temp_project_dir}")
        assert response.status_code == 200
        data = response.json()
        assert data["indexes"] == mock_list_index_projections.return_value
        mock_list_index_projections.assert_called_once_with(Path(str(temp_project_dir)))

    @patch("api.routes_management.refresh_project_knowledge")
    def test_refresh_indexes_returns_refresh_summary(
        self,
        mock_refresh_project_knowledge,
        client,
        temp_project_dir,
    ):
        """POST /api/indexes/refresh should report totals and updates."""
        mock_refresh_project_knowledge.return_value = {
            "scenes": [{"scene_path": "text/chapter-01.txt", "updated": True}],
            "indexes": [{"index_name": "CANON.md", "updated": True}],
            "scene_total": 1,
            "scene_updated": 1,
            "index_total": 1,
            "index_updated": 1,
        }

        response = client.post(
            "/api/indexes/refresh",
            json={"project_path": str(temp_project_dir)},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deprecated"] is True
        assert data["replacement"] == "/api/knowledge/refresh"
        assert data["index_total"] == 1
        assert data["indexes"] == mock_refresh_project_knowledge.return_value["indexes"]
        assert mock_refresh_project_knowledge.call_count == 1
        assert mock_refresh_project_knowledge.call_args[0][0] == Path(str(temp_project_dir))

    @patch("api.routes_management.get_stale_indexes")
    @patch("api.routes_management.list_index_projections")
    def test_indexes_status_returns_stale_index_summary(
        self,
        mock_list_index_projections,
        mock_get_stale_indexes,
        client,
        temp_project_dir,
    ):
        """GET /api/indexes/status returns stale keys and projection count."""
        mock_get_stale_indexes.return_value = ["CANON.md"]
        mock_list_index_projections.return_value = [
            {"index_name": "CANON.md"},
            {"index_name": "STYLE.md"},
        ]

        response = client.get(f"/api/indexes/status?project_path={temp_project_dir}")
        assert response.status_code == 200
        data = response.json()
        assert data == {
            "stale_indexes": ["CANON.md"],
            "stale_count": 1,
            "projected_count": 2,
            "deprecated": True,
            "replacement": "/api/knowledge/refresh",
        }
        mock_get_stale_indexes.assert_called_once_with(Path(str(temp_project_dir)))
        mock_list_index_projections.assert_called_once_with(Path(str(temp_project_dir)))

    @patch("api.routes_management.refresh_project_knowledge")
    def test_project_refresh_returns_orchestrator_payload(
        self,
        mock_refresh_project_knowledge,
        client,
        temp_project_dir,
    ):
        """POST /api/project/refresh proxies refresh payload."""
        mock_refresh_project_knowledge.return_value = {
            "scenes": [{"scene_path": "text/chapter-01.txt", "updated": True}],
            "indexes": [{"index_name": "CANON.md", "updated": True}],
            "scene_total": 1,
            "scene_updated": 1,
            "index_total": 1,
            "index_updated": 1,
        }

        response = client.post(
            "/api/project/refresh",
            json={"project_path": str(temp_project_dir)},
        )
        assert response.status_code == 200
        assert response.json() == mock_refresh_project_knowledge.return_value
        mock_refresh_project_knowledge.assert_called_once_with(Path(str(temp_project_dir)))

    @patch("api.routes_management.refresh_project_knowledge")
    def test_knowledge_refresh_returns_orchestrator_payload(
        self,
        mock_refresh_project_knowledge,
        client,
        temp_project_dir,
    ):
        """POST /api/knowledge/refresh proxies refresh payload."""
        mock_refresh_project_knowledge.return_value = {
            "scenes": [{"scene_path": "text/chapter-01.txt", "updated": True}],
            "indexes": [{"index_name": "CANON.md", "updated": True}],
            "scene_total": 1,
            "scene_updated": 1,
            "index_total": 1,
            "index_updated": 1,
            "chain_warnings": [],
            "extraction": {"scenes_processed": 1, "failed_scenes": []},
        }

        response = client.post(
            "/api/knowledge/refresh",
            json={"project_path": str(temp_project_dir)},
        )

        assert response.status_code == 200
        assert response.json() == mock_refresh_project_knowledge.return_value
        mock_refresh_project_knowledge.assert_called_once_with(Path(str(temp_project_dir)))

    @patch("api.routes_management.reset_all_knowledge")
    def test_reset_all_knowledge_returns_reset_true(
        self,
        mock_reset_all_knowledge,
        client,
        temp_project_dir,
    ):
        """DELETE /api/knowledge should delete all knowledge and return reset: True."""
        response = client.delete(f"/api/knowledge?project_path={temp_project_dir}")

        assert response.status_code == 200
        assert response.json() == {"reset": True}
        mock_reset_all_knowledge.assert_called_once_with(Path(str(temp_project_dir)))

    def test_reset_all_knowledge_nonexistent_project_404(self, client):
        """DELETE /api/knowledge should return 404 for nonexistent project."""
        response = client.delete("/api/knowledge?project_path=/nonexistent/path")
        assert response.status_code == 404

    @patch("api.routes_management.get_passive_connection")
    @patch("api.routes_management.get_knowledge_review")
    def test_get_knowledge_review_returns_category_payload(
        self,
        mock_get_knowledge_review,
        mock_get_passive_connection,
        client,
        temp_project_dir,
    ):
        """GET /api/knowledge/review returns extracted entities + overrides."""
        mock_get_passive_connection.return_value = MagicMock()
        mock_get_knowledge_review.return_value = {
            "category": "characters",
            "entity_key_field": "name",
            "items": [{"name": "Aria Vale"}],
            "overrides": [{"entity_key": "Aria Vale", "field_name": "traits", "value": "focused"}],
        }

        response = client.get(
            "/api/knowledge/review"
            f"?category=characters&project_path={temp_project_dir}"
        )

        assert response.status_code == 200
        assert response.json() == mock_get_knowledge_review.return_value
        mock_get_knowledge_review.assert_called_once()
        _, category_arg = mock_get_knowledge_review.call_args[0]
        assert category_arg == "characters"

    @patch("api.routes_management.submit_override")
    def test_submit_knowledge_override_returns_updated(
        self,
        mock_submit_override,
        client,
        temp_project_dir,
    ):
        """POST /api/knowledge/override stores one override field."""
        response = client.post(
            "/api/knowledge/override",
            json={
                "project_path": str(temp_project_dir),
                "category": "characters",
                "entity_key": "Aria Vale",
                "field_name": "traits",
                "value": "focused",
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "updated": True,
            "category": "characters",
            "entity_key": "Aria Vale",
            "field_name": "traits",
        }
        mock_submit_override.assert_called_once()

    @patch("api.routes_management.delete_knowledge_override")
    def test_delete_knowledge_override_returns_deleted(
        self,
        mock_delete_override,
        client,
        temp_project_dir,
    ):
        """DELETE /api/knowledge/override deletes one override field."""
        mock_delete_override.return_value = True

        response = client.request(
            "DELETE",
            "/api/knowledge/override",
            json={
                "project_path": str(temp_project_dir),
                "category": "characters",
                "entity_key": "Aria Vale",
                "field_name": "traits",
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "deleted": True,
            "category": "characters",
            "entity_key": "Aria Vale",
            "field_name": "traits",
        }
        mock_delete_override.assert_called_once()

    @patch("api.routes_management.export_knowledge_markdown")
    def test_export_knowledge_returns_markdown(
        self,
        mock_export_knowledge,
        client,
        temp_project_dir,
    ):
        """POST /api/knowledge/export returns markdown payload."""
        mock_export_knowledge.return_value = "# Knowledge Export\n\n## Characters"

        response = client.post(
            "/api/knowledge/export",
            json={"project_path": str(temp_project_dir)},
        )

        assert response.status_code == 200
        assert response.json() == {"markdown": "# Knowledge Export\n\n## Characters"}
        mock_export_knowledge.assert_called_once()

    @patch("api.routes_management.get_project_knowledge_status")
    def test_project_status_returns_knowledge_summary(
        self,
        mock_get_project_knowledge_status,
        client,
        temp_project_dir,
    ):
        """GET /api/project/status proxies knowledge freshness payload."""
        mock_get_project_knowledge_status.return_value = {
            "scenes": {"total": 2, "stale": 1, "fresh": 1, "last_refreshed_at": None},
            "indexes": {"total": 3, "stale": 0, "fresh": 3, "last_refreshed_at": None},
            "stale_total": 1,
            "fresh_total": 4,
        }

        response = client.get(f"/api/project/status?project_path={temp_project_dir}")
        assert response.status_code == 200
        assert response.json() == mock_get_project_knowledge_status.return_value
        mock_get_project_knowledge_status.assert_called_once_with(Path(str(temp_project_dir)))

    def test_project_status_nonexistent_project_404(self, client):
        """Project status endpoint should return 404 for missing project directory."""
        response = client.get("/api/project/status?project_path=/nonexistent/path")
        assert response.status_code == 404

    # --- Learning Management Tests ---

    def test_get_learning_returns_all_categories(self, client, temp_project_dir):
        """GET /api/learning should return all learning categories."""
        from orchestrator.runtime.db import get_connection, LearningStore

        conn = get_connection(temp_project_dir)
        try:
            LearningStore.add_preference(conn, "Test preference")
            LearningStore.add_blind_spot(conn, "Test blind spot")
            LearningStore.increment_review_count(conn)
        finally:
            conn.close()

        response = client.get(f"/api/learning?project_path={temp_project_dir}")
        assert response.status_code == 200
        data = response.json()
        assert 'preferences' in data
        assert 'blind_spots' in data
        assert 'resolutions' in data
        assert 'ambiguity_intentional' in data
        assert 'ambiguity_accidental' in data
        assert 'review_count' in data
        assert len(data['preferences']) == 1
        assert len(data['blind_spots']) == 1

    def test_get_learning_nonexistent_project_404(self, client):
        """Should return 404 for nonexistent project."""
        response = client.get("/api/learning?project_path=/nonexistent/path")
        assert response.status_code == 404

    def test_get_learning_empty_project_does_not_create_db(self, client, temp_project_dir):
        """Passive startup learning load should not create lit-critic.db."""
        from orchestrator.runtime.config import DB_FILE

        db_path = temp_project_dir / DB_FILE
        assert db_path.exists() is False

        response = client.get(f"/api/learning?project_path={temp_project_dir}")

        assert response.status_code == 200
        data = response.json()
        assert data['project_name'] == 'Unknown'
        assert data['review_count'] == 0
        assert data['preferences'] == []
        assert db_path.exists() is False

    def test_export_learning_creates_file(self, client, temp_project_dir):
        """POST /api/learning/export should create LEARNING.md."""
        from orchestrator.runtime.db import get_connection, LearningStore

        conn = get_connection(temp_project_dir)
        try:
            LearningStore.add_preference(conn, "Test preference")
        finally:
            conn.close()

        response = client.post("/api/learning/export", json={
            "project_path": str(temp_project_dir)
        })
        assert response.status_code == 200
        data = response.json()
        assert data['exported'] is True
        assert 'path' in data

        # Verify file exists
        learning_file = temp_project_dir / "LEARNING.md"
        assert learning_file.exists()

    def test_export_learning_returns_path(self, client, temp_project_dir):
        """Export should return the file path."""
        response = client.post("/api/learning/export", json={
            "project_path": str(temp_project_dir)
        })
        assert response.status_code == 200
        data = response.json()
        assert str(temp_project_dir / "LEARNING.md") in data['path']

    def test_reset_learning_clears_all_data(self, client, temp_project_dir):
        """DELETE /api/learning should reset all learning data."""
        from orchestrator.runtime.db import get_connection, LearningStore
        from orchestrator.services import load_learning

        conn = get_connection(temp_project_dir)
        try:
            LearningStore.add_preference(conn, "Pref 1")
            LearningStore.add_preference(conn, "Pref 2")
            LearningStore.add_blind_spot(conn, "Blind spot")
        finally:
            conn.close()

        response = client.delete(f"/api/learning?project_path={temp_project_dir}")
        assert response.status_code == 200
        data = response.json()
        assert data['reset'] is True

        # Verify all data is gone
        learning = load_learning(temp_project_dir)
        assert learning.preferences == []
        assert learning.blind_spots == []

    def test_reset_learning_nonexistent_project_404(self, client):
        """Should return 404 for nonexistent project."""
        response = client.delete("/api/learning?project_path=/nonexistent/path")
        assert response.status_code == 404

    def test_delete_learning_entry_returns_deleted_true(self, client, temp_project_dir):
        """DELETE /api/learning/entries/{id} should delete entry and return True."""
        from orchestrator.runtime.db import get_connection, LearningStore
        from orchestrator.services import load_learning

        conn = get_connection(temp_project_dir)
        try:
            LearningStore.add_preference(conn, "Preference 1")
            LearningStore.add_preference(conn, "Preference 2")
        finally:
            conn.close()

        learning = load_learning(temp_project_dir)
        entry_id = learning.preferences[0]['id']

        response = client.delete(f"/api/learning/entries/{entry_id}?project_path={temp_project_dir}")
        assert response.status_code == 200
        data = response.json()
        assert data['deleted'] is True
        assert data['entry_id'] == entry_id

        # Verify one remains
        learning_after = load_learning(temp_project_dir)
        assert len(learning_after.preferences) == 1

    def test_delete_learning_entry_not_found_404(self, client, temp_project_dir):
        """Should return 404 when deleting nonexistent entry."""
        response = client.delete(f"/api/learning/entries/9999?project_path={temp_project_dir}")
        assert response.status_code == 404


class TestAnalyzableScenesEndpoint:
    """Tests for GET /api/scenes/analyzable."""

    @patch("api.routes_management.get_passive_connection")
    @patch("api.routes_management.list_analyzable_scenes")
    def test_returns_analyzable_scenes(
        self,
        mock_list_analyzable_scenes,
        mock_get_passive_connection,
        client,
        temp_project_dir,
    ):
        """Returns analyzable scenes when DB exists and scenes are ready."""
        mock_get_passive_connection.return_value = MagicMock()
        mock_list_analyzable_scenes.return_value = [
            {
                "scene_key": "text/chapter-01.md",
                "path": "/project/text/chapter-01.md",
                "status": "extracted",
            }
        ]

        response = client.get(f"/api/scenes/analyzable?project_path={temp_project_dir}")
        assert response.status_code == 200
        data = response.json()
        assert "analyzable_scenes" in data
        assert len(data["analyzable_scenes"]) == 1
        assert data["analyzable_scenes"][0]["scene_key"] == "text/chapter-01.md"
        assert data["analyzable_scenes"][0]["status"] == "extracted"
        mock_list_analyzable_scenes.assert_called_once()

    @patch("api.routes_management.get_passive_connection")
    def test_no_db_returns_empty_list(
        self,
        mock_get_passive_connection,
        client,
        temp_project_dir,
    ):
        """When DB does not exist yet (get_passive_connection returns None), returns empty list."""
        mock_get_passive_connection.return_value = None

        response = client.get(f"/api/scenes/analyzable?project_path={temp_project_dir}")
        assert response.status_code == 200
        data = response.json()
        assert data == {"analyzable_scenes": []}

    @patch("api.routes_management.get_passive_connection")
    @patch("api.routes_management.list_analyzable_scenes")
    def test_all_analyzed_returns_empty_list(
        self,
        mock_list_analyzable_scenes,
        mock_get_passive_connection,
        client,
        temp_project_dir,
    ):
        """Returns empty list when all scenes are already analyzed."""
        mock_get_passive_connection.return_value = MagicMock()
        mock_list_analyzable_scenes.return_value = []

        response = client.get(f"/api/scenes/analyzable?project_path={temp_project_dir}")
        assert response.status_code == 200
        assert response.json() == {"analyzable_scenes": []}

    def test_missing_project_returns_404(self, client):
        """Non-existent project_path → 404."""
        response = client.get("/api/scenes/analyzable?project_path=/no/such/path")
        assert response.status_code == 404

    @patch("api.routes_management.get_passive_connection")
    @patch("api.routes_management.list_analyzable_scenes")
    def test_extraction_due_scene_included(
        self,
        mock_list_analyzable_scenes,
        mock_get_passive_connection,
        client,
        temp_project_dir,
    ):
        """extraction_due scenes appear in the response."""
        mock_get_passive_connection.return_value = MagicMock()
        mock_list_analyzable_scenes.return_value = [
            {
                "scene_key": "text/chapter-01.md",
                "path": "/project/text/chapter-01.md",
                "status": "extraction_due",
            }
        ]

        response = client.get(f"/api/scenes/analyzable?project_path={temp_project_dir}")
        assert response.status_code == 200
        data = response.json()
        assert data["analyzable_scenes"][0]["status"] == "extraction_due"
