"""
Tests for config and repo-preflight routes.
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


class TestConfigEndpoint:
    """Test the /api/config endpoint."""

    def test_config_no_api_key(self, client):
        """Config reports no key when env vars are unset."""
        import os
        anthropic_backup = os.environ.pop("ANTHROPIC_API_KEY", None)
        openai_backup = os.environ.pop("OPENAI_API_KEY", None)
        try:
            response = client.get("/api/config")
            assert response.status_code == 200
            assert response.json()["api_key_configured"] is False
        finally:
            if anthropic_backup:
                os.environ["ANTHROPIC_API_KEY"] = anthropic_backup
            if openai_backup:
                os.environ["OPENAI_API_KEY"] = openai_backup

    def test_config_with_api_key(self, client):
        """Config reports key present when env var is set."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            response = client.get("/api/config")
            assert response.status_code == 200
            assert response.json()["api_key_configured"] is True

    def test_config_returns_available_models(self, client):
        """Config returns available models with labels."""
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "available_models" in data
        assert "default_model" in data
        # All expected models are present
        models = data["available_models"]
        assert "sonnet" in models
        assert "opus" in models
        assert "haiku" in models
        # Each model has a label
        for name, info in models.items():
            assert "label" in info, f"Model '{name}' missing label"

    def test_config_default_model_is_valid(self, client):
        """Default model must be one of the available models."""
        response = client.get("/api/config")
        data = response.json()
        assert data["default_model"] in data["available_models"]

    def test_config_models_include_provider(self, client):
        """Each model in config should include its provider."""
        response = client.get("/api/config")
        data = response.json()
        for name, info in data["available_models"].items():
            assert "provider" in info, f"Model '{name}' missing provider"
            assert info["provider"] in ("anthropic", "openai")

    def test_config_models_include_id_and_max_tokens(self, client):
        """Each model in config should include id and max_tokens for richer clients."""
        response = client.get("/api/config")
        data = response.json()
        for name, info in data["available_models"].items():
            assert "id" in info, f"Model '{name}' missing id"
            assert isinstance(info["id"], str)
            assert "max_tokens" in info, f"Model '{name}' missing max_tokens"
            assert isinstance(info["max_tokens"], int)
            assert info["max_tokens"] > 0

    def test_config_includes_model_registry_status(self, client):
        """Config should include non-secret model registry diagnostics."""
        response = client.get("/api/config")
        data = response.json()
        assert "model_registry" in data
        registry = data["model_registry"]
        assert "auto_discovery_enabled" in registry
        assert "cache_path" in registry
        assert "ttl_seconds" in registry

    def test_config_includes_openai_models(self, client):
        """Config should include at least one OpenAI model."""
        response = client.get("/api/config")
        data = response.json()
        openai_models = [n for n, i in data["available_models"].items() if i["provider"] == "openai"]
        assert len(openai_models) >= 1

    def test_config_reports_per_provider_keys(self, client):
        """Config should report api_keys_configured per provider."""
        response = client.get("/api/config")
        data = response.json()
        assert "api_keys_configured" in data
        assert "anthropic" in data["api_keys_configured"]
        assert "openai" in data["api_keys_configured"]

    def test_config_openai_key_detection(self, client):
        """Config should detect OPENAI_API_KEY when set."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-oai"}):
            response = client.get("/api/config")
            data = response.json()
            assert data["api_keys_configured"]["openai"] is True

    def test_config_includes_mode_cost_hints(self, client):
        """Config should expose mode-level cost hint strings for UI rendering."""
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "mode_cost_hints" in data
        assert set(data["mode_cost_hints"].keys()) == {"quick", "deep"}
        assert isinstance(data["mode_cost_hints"]["quick"], str)

    def test_config_includes_scene_discovery_defaults(self, client):
        """Config should expose default + effective scene discovery settings."""
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()

        assert data["default_scene_folder"] == "text"
        assert data["default_scene_extensions"] == ["txt"]
        assert isinstance(data["scene_folder"], str)
        assert isinstance(data["scene_extensions"], list)

    @patch("api.routes_config.set_scene_discovery_settings")
    @patch("api.routes_config.get_scene_discovery_settings")
    def test_update_config_persists_scene_discovery_settings(
        self,
        mock_get_scene_discovery_settings,
        mock_set_scene_discovery_settings,
        client,
    ):
        """POST /api/config should persist and return scene discovery settings."""
        mock_get_scene_discovery_settings.return_value = ("drafts", ("md", "txt"))

        response = client.post(
            "/api/config",
            json={"scene_folder": "drafts", "scene_extensions": ["md", "txt"]},
        )

        assert response.status_code == 200
        mock_set_scene_discovery_settings.assert_called_once_with("drafts", ["md", "txt"])

        data = response.json()
        assert data["scene_folder"] == "drafts"
        assert data["scene_extensions"] == ["md", "txt"]
        assert data["default_scene_folder"] == "text"
        assert data["default_scene_extensions"] == ["txt"]


class TestRepoPreflightEndpoints:
    """Test repo-path preflight status and update routes."""

    @patch("api.route_helpers.get_repo_path")
    @patch("api.route_helpers.validate_repo_path")
    def test_repo_preflight_returns_status_payload(self, mock_validate, mock_get_repo_path, client):
        mock_get_repo_path.return_value = "C:/invalid/path"
        mock_validate.return_value = type("Result", (), {
            "ok": False,
            "reason_code": "not_found",
            "message": "Repository path was not found",
            "path": "C:/invalid/path",
        })()

        response = client.get("/api/repo-preflight")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert payload["reason_code"] == "not_found"
        assert payload["configured_path"] == "C:/invalid/path"
        assert "marker" in payload

    @patch("api.routes_config.set_repo_path")
    @patch("api.route_helpers.validate_repo_path")
    @patch("api.routes_config.validate_repo_path")
    @patch("api.route_helpers.get_repo_path")
    def test_repo_path_update_persists_when_valid(
        self,
        mock_get_repo_path,
        mock_validate_config,
        mock_validate_helpers,
        mock_set_repo_path,
        client,
    ):
        valid_input = "C:/lit-critic"
        mock_get_repo_path.return_value = valid_input
        valid_result = type("Result", (), {
            "ok": True,
            "reason_code": "",
            "message": "Repository path is valid.",
            "path": valid_input,
        })()
        mock_validate_config.return_value = valid_result
        mock_validate_helpers.return_value = valid_result

        response = client.post("/api/repo-path", json={"repo_path": valid_input})
        assert response.status_code == 200
        mock_set_repo_path.assert_called_once_with(valid_input)
        assert response.json()["ok"] is True

    @patch("api.routes_config.validate_repo_path")
    def test_repo_path_update_rejects_invalid(self, mock_validate, client):
        mock_validate.return_value = type("Result", (), {
            "ok": False,
            "reason_code": "missing_marker",
            "message": "Repository directory does not contain lit-critic-server.py",
            "path": "C:/somewhere",
        })()

        response = client.post("/api/repo-path", json={"repo_path": "C:/somewhere"})
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "repo_path_invalid"
        assert detail["reason_code"] == "missing_marker"

    @patch("api.routes_analysis._ensure_repo_preflight_ready")
    def test_analyze_blocks_when_repo_preflight_invalid(self, mock_preflight, client, reset_session):
        mock_preflight.side_effect = HTTPException(
            status_code=409,
            detail={"code": "repo_path_invalid", "message": "invalid repo path"},
        )

        response = client.post("/api/analyze", json={
            "scene_path": "/any/scene.txt",
            "project_path": "/any/project",
            "api_key": "sk-ant-explicit",
        })
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "repo_path_invalid"


