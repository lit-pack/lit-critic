"""Integration tests for web.routes_explain — Explain This endpoint (Task D1/D3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.app import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_FINDING_STUB: dict = {
    "number": 1,
    "severity": "major",
    "lens": "prose",
    "location": "Paragraph 1",
    "evidence": "Repeated sentence starts",
    "impact": "Creates monotony",
    "options": ["Vary openings", "Use different constructions"],
    "flagged_by": ["prose"],
}

_SCENE_TEXT = "She walked. She talked. She stopped. She sat down."


def _post_explain(client, finding_id: int, depth: str = "quick", project_path: str = "/tmp/proj",
                  scene_text: str = _SCENE_TEXT, finding: dict | None = None) -> dict:
    """Helper: POST /api/findings/{id}/explain and return response JSON."""
    resp = client.post(
        f"/api/findings/{finding_id}/explain",
        params={"project_path": project_path},
        json={
            "depth": depth,
            "finding": finding or _FINDING_STUB,
            "scene_text": scene_text,
        },
    )
    return resp


# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


def test_explain_quick_returns_200_and_explanation(client, tmp_path):
    """POST with depth=quick returns 200 with explanation text."""
    expected_explanation = "The prose rhythm breaks because of repeated sentence starts."

    with patch("api.routes_explain._build_client", return_value=(None, "claude-haiku-mock")), \
         patch("api.routes_explain.core_service.explain_finding",
               AsyncMock(return_value=expected_explanation)):
        resp = _post_explain(client, finding_id=1, depth="quick",
                             project_path=str(tmp_path))

    assert resp.status_code == 200
    data = resp.json()
    assert data["finding_id"] == 1
    assert data["depth"] == "quick"
    assert data["explanation"] == expected_explanation
    assert data["model_used"] == "claude-haiku-mock"


def test_explain_deep_returns_200(client, tmp_path):
    """POST with depth=deep returns 200 with explanation text."""
    with patch("api.routes_explain._build_client", return_value=(None, "claude-frontier-mock")), \
         patch("api.routes_explain.core_service.explain_finding",
               AsyncMock(return_value="Deep literary explanation.")):
        resp = _post_explain(client, finding_id=7, depth="deep",
                             project_path=str(tmp_path))

    assert resp.status_code == 200
    data = resp.json()
    assert data["finding_id"] == 7
    assert data["depth"] == "deep"
    assert data["explanation"] == "Deep literary explanation."


def test_explain_finding_id_reflected_in_response(client, tmp_path):
    """The finding_id in the path is echoed in the response."""
    with patch("api.routes_explain._build_client", return_value=(None, "model")), \
         patch("api.routes_explain.core_service.explain_finding",
               AsyncMock(return_value="Explanation.")):
        for fid in [1, 42, 999]:
            resp = _post_explain(client, finding_id=fid, project_path=str(tmp_path))
            assert resp.status_code == 200
            assert resp.json()["finding_id"] == fid


def test_explain_calls_service_with_correct_args(client, tmp_path):
    """explain_finding is called with the scene text and finding from the request body."""
    mock_explain = AsyncMock(return_value="Called.")
    custom_finding = dict(_FINDING_STUB, number=5, lens="continuity")
    scene = "A custom scene text."

    with patch("api.routes_explain._build_client", return_value=(None, "model")), \
         patch("api.routes_explain.core_service.explain_finding", mock_explain):
        _post_explain(client, finding_id=5, project_path=str(tmp_path),
                      scene_text=scene, finding=custom_finding)

    mock_explain.assert_called_once()
    call_kwargs = mock_explain.call_args.kwargs
    assert call_kwargs["scene_text"] == scene
    assert call_kwargs["finding_dict"]["number"] == 5
    assert call_kwargs["finding_dict"]["lens"] == "continuity"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_explain_no_api_key_returns_400(client, tmp_path):
    """Returns 400 when no API key is configured for the model provider."""
    with patch("api.routes_explain._build_client",
               side_effect=HTTPException(status_code=400, detail="No API key configured")):
        resp = _post_explain(client, finding_id=3, project_path=str(tmp_path))

    assert resp.status_code == 400
    assert "API key" in resp.json().get("detail", "")


def test_explain_llm_failure_returns_500(client, tmp_path):
    """Returns 500 when the LLM call raises an unexpected error."""
    with patch("api.routes_explain._build_client", return_value=(None, "model")), \
         patch("api.routes_explain.core_service.explain_finding",
               AsyncMock(side_effect=RuntimeError("LLM backend unavailable"))):
        resp = _post_explain(client, finding_id=5, project_path=str(tmp_path))

    assert resp.status_code == 500
    assert "Explanation generation failed" in resp.json().get("detail", "")


def test_explain_invalid_depth_returns_422(client, tmp_path):
    """Invalid depth value returns 422 Unprocessable Entity."""
    resp = client.post(
        "/api/findings/1/explain",
        params={"project_path": str(tmp_path)},
        json={
            "depth": "ultra",          # not in Literal["quick", "deep"]
            "finding": _FINDING_STUB,
            "scene_text": _SCENE_TEXT,
        },
    )
    assert resp.status_code == 422


def test_explain_missing_project_path_returns_422(client):
    """Missing required project_path query param returns 422."""
    resp = client.post(
        "/api/findings/1/explain",
        # No project_path param
        json={"depth": "quick", "finding": _FINDING_STUB, "scene_text": _SCENE_TEXT},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Model resolution helpers
# ---------------------------------------------------------------------------


def test_resolve_model_name_uses_override():
    """If an explicit model name is provided, it is returned directly."""
    from api.routes_explain import _resolve_model_name
    assert _resolve_model_name("quick", "gpt-4-override") == "gpt-4-override"
    assert _resolve_model_name("deep", "my-custom-model") == "my-custom-model"


def test_resolve_model_name_quick_falls_back_to_haiku(monkeypatch):
    """Quick depth falls back to claude-haiku when the 'quick' slot is not configured."""
    from api import routes_explain

    def _bad_resolve(model_name):
        raise ValueError(f"Unknown model: {model_name}")

    monkeypatch.setattr(routes_explain, "resolve_model", _bad_resolve)
    result = routes_explain._resolve_model_name("quick", None)
    assert result == "claude-haiku"


def test_resolve_model_name_deep_falls_back_to_sonnet(monkeypatch):
    """Deep depth falls back to claude-3-5-sonnet when the 'frontier' slot is not configured."""
    from api import routes_explain

    def _bad_resolve(model_name):
        raise ValueError(f"Unknown model: {model_name}")

    monkeypatch.setattr(routes_explain, "resolve_model", _bad_resolve)
    result = routes_explain._resolve_model_name("deep", None)
    assert result == "claude-3-5-sonnet"
