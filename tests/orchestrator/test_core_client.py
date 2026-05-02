"""Tests for the Platform Core HTTP client adapter."""

import io
import json
from urllib import error

import pytest

from contracts.v1.schemas import AnalyzeModelConfig, AnalyzeRequest, IndexesContract
from orchestrator.core_client import CoreClient, CoreClientError, CoreClientHTTPError


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeRawHTTPResponse:
    def __init__(self, raw: str):
        self._raw = raw.encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_health_success(monkeypatch):
    client = CoreClient(base_url="http://core.local")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=0: _FakeHTTPResponse({"status": "ok"}),
    )

    assert client.health() == {"status": "ok"}


def test_analyze_parses_contract(monkeypatch):
    client = CoreClient(base_url="http://core.local")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=0: _FakeHTTPResponse(
            {
                "findings": [],
                "glossary_issues": [],
                "meta": {"model_used": "claude-sonnet-4-5-20250929"},
            }
        ),
    )
    req = AnalyzeRequest(
        scene_text="Scene",
        indexes=IndexesContract(),
        model_settings=AnalyzeModelConfig(
            analysis_model="sonnet",
            api_keys={"anthropic": "sk-ant-test"},
            max_tokens=512,
        ),
    )

    res = client.analyze(req)
    assert res.meta.model_used == "claude-sonnet-4-5-20250929"


def test_http_error_maps_to_core_http_error(monkeypatch):
    client = CoreClient(base_url="http://core.local")

    def _raise_http(*args, **kwargs):
        raise error.HTTPError(
            url="http://core.local/v1/analyze",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise_http)

    with pytest.raises(CoreClientHTTPError) as exc:
        client.health()

    assert exc.value.status_code == 400


def test_url_error_raises_core_client_error(monkeypatch):
    client = CoreClient(base_url="http://core.local", retry_attempts=1)

    def _raise_url(*args, **kwargs):
        raise error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _raise_url)

    with pytest.raises(CoreClientError):
        client.health()


def test_retry_exhaustion_on_5xx_raises_http_error(monkeypatch):
    client = CoreClient(base_url="http://core.local", retry_attempts=3, retry_backoff_seconds=0)
    calls = {"count": 0}

    def _raise_http(*args, **kwargs):
        calls["count"] += 1
        raise error.HTTPError(
            url="http://core.local/health",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"temporarily unavailable"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise_http)

    with pytest.raises(CoreClientHTTPError) as exc:
        client.health()

    assert exc.value.status_code == 503
    assert calls["count"] == 3


def test_invalid_json_raises_core_client_error(monkeypatch):
    client = CoreClient(base_url="http://core.local", retry_attempts=1)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=0: _FakeRawHTTPResponse("{not-json"),
    )

    with pytest.raises(CoreClientError) as exc:
        client.health()

    assert "invalid JSON" in str(exc.value)
