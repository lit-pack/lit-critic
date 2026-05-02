"""Platform -> Core seam integration tests (real Core app, stubbed LLM)."""

import io
from urllib import error
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

import core.api as core_api
from contracts.v1.schemas import IndexesContract
from orchestrator.core_client import CoreClient, CoreClientHTTPError
from orchestrator.facade import PlatformFacade
from orchestrator.runtime.llm.base import LLMResponse, LLMToolResponse


class _FakeLLMClient:
    async def create_message(self, **kwargs):
        return LLMResponse(text="[]")

    async def create_message_with_tool(self, **kwargs):
        return LLMToolResponse(
            tool_input={
                "glossary_issues": [],
                "summary": {
                    "prose": {"critical": 0, "major": 1, "minor": 0},
                    "structure": {"critical": 0, "major": 0, "minor": 0},
                    "coherence": {"critical": 0, "major": 0, "minor": 0},
                },
                "conflicts": [],
                "ambiguities": [],
                "findings": [
                    {
                        "number": 1,
                        "severity": "major",
                        "lens": "prose",
                        "location": "Paragraph 1",
                        "line_start": 1,
                        "line_end": 1,
                        "evidence": "Repeated sentence openings",
                        "impact": "Monotony",
                        "options": ["Vary openings"],
                        "flagged_by": ["prose"],
                        "ambiguity_type": None,
                        "origin": "llm",
                    }
                ],
            }
        )

    async def stream_message(self, **kwargs):  # pragma: no cover - not used in this seam test
        if False:
            yield ""


class _BridgeResponse:
    def __init__(self, content: bytes):
        self._content = content

    def read(self):
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _build_urlopen_bridge(test_client: TestClient):
    def _urlopen(req, timeout=0):
        method = req.get_method()
        split = urlsplit(req.full_url)
        path = split.path + (f"?{split.query}" if split.query else "")
        response = test_client.request(
            method,
            path,
            content=req.data,
            headers=dict(req.headers.items()),
        )
        if response.status_code >= 400:
            raise error.HTTPError(
                url=req.full_url,
                code=response.status_code,
                msg=response.reason_phrase,
                hdrs=None,
                fp=io.BytesIO(response.content),
            )
        return _BridgeResponse(response.content)

    return _urlopen


def test_platform_facade_analyze_calls_real_core_app_with_stubbed_llm(monkeypatch):
    """PlatformFacade + CoreClient go through real FastAPI Core app surface."""
    monkeypatch.setattr(core_api, "create_client", lambda provider, api_key: _FakeLLMClient())
    client = TestClient(core_api.app)
    monkeypatch.setattr("urllib.request.urlopen", _build_urlopen_bridge(client))

    facade = PlatformFacade(core_client=CoreClient(base_url="http://core.local"))
    result = facade.analyze_scene_text(
        scene_text="Scene text",
        indexes=IndexesContract(),
        analysis_model="sonnet",
        api_keys={"anthropic": "sk-ant-test"},
        max_tokens=512,
    )

    assert len(result.findings) == 1
    assert result.findings[0].lens == "prose"
    assert result.findings[0].severity == "major"


def test_platform_core_seam_surfaces_core_http_errors(monkeypatch):
    """Platform->Core seam should map Core HTTP failures to CoreClientHTTPError."""
    monkeypatch.setattr(core_api, "create_client", lambda provider, api_key: _FakeLLMClient())
    client = TestClient(core_api.app)
    monkeypatch.setattr("urllib.request.urlopen", _build_urlopen_bridge(client))

    facade = PlatformFacade(core_client=CoreClient(base_url="http://core.local", retry_attempts=1))

    with pytest.raises(CoreClientHTTPError) as exc:
        facade.analyze_scene_text(
            scene_text="Scene text",
            indexes=IndexesContract(),
            analysis_model="not-a-real-model",
            api_keys={"anthropic": "sk-ant-test"},
            max_tokens=512,
        )

    assert exc.value.status_code == 400
