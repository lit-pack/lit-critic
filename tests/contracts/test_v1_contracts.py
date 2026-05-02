"""Contract validation and compatibility parity tests for contracts.v1."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from contracts.v1.adapters import (
    adapt_analyze_request_to_legacy,
    adapt_discuss_request_to_legacy,
    adapt_legacy_analyze_output_to_response,
    adapt_legacy_discuss_output_to_response,
    adapt_legacy_re_evaluate_output_to_response,
)
from contracts.v1.schemas import (
    AnalyzeRequest,
    DiscussRequest,
    ReEvaluateFindingRequest,
)
from contracts.v1.wrappers import run_analyze_contract_compatible
from orchestrator.runtime.llm.base import LLMResponse


GOLDEN_DIR = Path(__file__).parent / "golden"


def _golden(name: str) -> dict:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


def _sample_finding() -> dict:
    return {
        "number": 1,
        "severity": "major",
        "lens": "prose",
        "location": "Paragraph 1",
        "line_start": 3,
        "line_end": 5,
        "evidence": "Repetitive starts",
        "impact": "Rhythm flattens",
        "options": ["Vary openings"],
        "flagged_by": ["prose"],
        "ambiguity_type": None,
        "stale": False,
    }


class TestSchemaValidation:
    def test_analyze_request_valid(self):
        req = AnalyzeRequest.model_validate(
            {
                "scene_text": "Scene body",
                "indexes": {
                    "CANON": "canon",
                    "CAST": "cast",
                    "GLOSSARY": "glossary",
                },
                "learning_context": {"review_count": 2},
                "model_config": {
                    "analysis_model": "claude-sonnet-4-5-20250929",
                    "api_keys": {"anthropic": "sk-ant-test"},
                    "max_tokens": 4096,
                },
            }
        )
        assert req.model_settings.max_tokens == 4096

    def test_discuss_request_valid(self):
        req = DiscussRequest.model_validate(
            {
                "scene_text": "Scene body",
                "finding": _sample_finding(),
                "discussion_context": {"prior": []},
                "author_message": "This is intentional",
                "model_config": {
                    "discussion_model": "claude-haiku-4-5-20251001",
                    "api_keys": {"anthropic": "sk-ant-test"},
                    "max_tokens": 1024,
                },
            }
        )
        assert req.finding.number == 1

    def test_re_evaluate_request_valid(self):
        req = ReEvaluateFindingRequest.model_validate(
            {
                "stale_finding": _sample_finding(),
                "updated_scene_text": "Updated scene",
                "minimal_context": {"note": "line moved"},
                "model_config": {
                    "analysis_model": "claude-sonnet-4-5-20250929",
                    "api_keys": {"anthropic": "sk-ant-test"},
                    "max_tokens": 1024,
                },
            }
        )
        assert req.stale_finding.severity == "major"

    def test_schema_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            AnalyzeRequest.model_validate(
                {
                    "scene_text": "Scene body",
                    "indexes": {},
                    "model_config": {
                        "analysis_model": "m",
                        "api_keys": {},
                        "max_tokens": 10,
                    },
                    "unexpected": True,
                }
            )


class TestAdaptersAndParity:
    def test_adapt_analyze_request_to_legacy(self):
        req = AnalyzeRequest.model_validate(
            {
                "scene_text": "Scene body",
                "indexes": {"CANON": "canon text", "CAST": "cast text"},
                "model_config": {
                    "analysis_model": "claude-sonnet-4-5-20250929",
                    "api_keys": {"anthropic": "sk-ant-test"},
                    "max_tokens": 111,
                },
            }
        )
        legacy = adapt_analyze_request_to_legacy(req)
        assert legacy["scene"] == "Scene body"
        assert legacy["indexes"]["CANON.md"] == "canon text"
        assert legacy["indexes"]["glossary"] == ""

    def test_adapt_discuss_request_to_legacy(self):
        req = DiscussRequest.model_validate(
            {
                "scene_text": "Scene body",
                "finding": _sample_finding(),
                "discussion_context": {"prior": ["x"]},
                "author_message": "Please justify",
                "model_config": {
                    "discussion_model": "claude-haiku-4-5-20251001",
                    "api_keys": {"anthropic": "sk-ant-test"},
                    "max_tokens": 222,
                },
            }
        )
        legacy = adapt_discuss_request_to_legacy(req)
        assert legacy["author_message"] == "Please justify"
        assert legacy["finding"]["number"] == 1

    def test_golden_analyze_parity(self):
        legacy = _golden("analyze_legacy_output.json")
        response = adapt_legacy_analyze_output_to_response(
            legacy,
            model_used="claude-sonnet-4-5-20250929",
        )
        assert len(response.findings) == len(legacy["findings"])
        assert response.findings[0].severity == legacy["findings"][0]["severity"]

    def test_golden_discuss_parity(self):
        legacy = _golden("discuss_legacy_output.json")
        response = adapt_legacy_discuss_output_to_response(
            legacy,
            model_used="claude-haiku-4-5-20251001",
        )
        assert response.assistant_response == legacy["response"]
        assert response.action.type == "revise"
        assert response.updated_finding is not None
        assert response.updated_finding.severity == "minor"

    def test_golden_re_evaluate_updated_parity(self):
        legacy = _golden("re_evaluate_legacy_output_updated.json")
        response = adapt_legacy_re_evaluate_output_to_response(
            legacy,
            model_used="claude-sonnet-4-5-20250929",
            original_finding=_sample_finding(),
        )
        assert response.status == "updated"
        assert response.updated_finding is not None

    def test_golden_re_evaluate_withdrawn_parity(self):
        legacy = _golden("re_evaluate_legacy_output_withdrawn.json")
        response = adapt_legacy_re_evaluate_output_to_response(
            legacy,
            model_used="claude-sonnet-4-5-20250929",
        )
        assert response.status == "withdrawn"
        assert response.reason == legacy["reason"]

class TestWrapperCompatibility:
    async def test_run_analyze_contract_compatible(self, monkeypatch):
        req = AnalyzeRequest.model_validate(
            {
                "scene_text": "Scene body",
                "indexes": {"CANON": "canon", "CAST": "cast"},
                "model_config": {
                    "analysis_model": "claude-sonnet-4-5-20250929",
                    "api_keys": {"anthropic": "sk-ant-test"},
                    "max_tokens": 300,
                },
            }
        )

        mock_run = AsyncMock(return_value=_golden("analyze_legacy_output.json"))
        monkeypatch.setattr("contracts.v1.wrappers.run_analysis", mock_run)

        mock_client = AsyncMock()
        mock_client.create_message = AsyncMock(return_value=LLMResponse(text="[]"))

        response = await run_analyze_contract_compatible(mock_client, req)

        assert response.meta.model_used == "claude-sonnet-4-5-20250929"
        assert len(response.findings) == 2
        mock_run.assert_awaited_once()
