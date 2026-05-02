"""Unit tests for core.service decoupled port orchestration."""

from __future__ import annotations

from contracts.v1.schemas import (
    AnalyzeModelConfig,
    AnalyzeRequest,
    FindingContract,
    IndexesContract,
    ReEvaluateFindingRequest,
)
from core.domain import CoreFinding
from core.service import analyze, re_evaluate, explain_finding


class _FakeAnalysisPort:
    async def analyze(self, **kwargs):
        return {
            "findings": [
                {
                    "number": 1,
                    "severity": "major",
                    "lens": "prose",
                    "location": "Paragraph 1",
                    "line_start": 1,
                    "line_end": 2,
                    "evidence": "Repeated starts",
                    "impact": "Monotony",
                    "options": ["Vary openings"],
                    "flagged_by": ["prose"],
                }
            ],
            "glossary_issues": [],
        }


class _FakeReEvalPort:
    async def re_evaluate(self, **kwargs):
        return {"status": "withdrawn", "reason": "No longer applies."}


async def test_analyze_uses_injected_analysis_port():
    req = AnalyzeRequest(
        scene_text="Scene",
        indexes=IndexesContract(),
        model_settings=AnalyzeModelConfig(
            analysis_model="claude-sonnet-4-5-20250929",
            api_keys={},
            max_tokens=512,
        ),
    )

    res = await analyze(req, client=object(), analysis_engine=_FakeAnalysisPort())

    assert len(res.findings) == 1
    assert res.findings[0].severity == "major"


# ---------------------------------------------------------------------------
# Fake port for explain_finding tests
# ---------------------------------------------------------------------------

class _FakeExplainPort:
    """Discussion port stub for one-shot explain calls."""

    def __init__(self, response: str = "Explanation."):
        self._response = response

    async def discuss(self, **kwargs):
        finding: CoreFinding = kwargs["finding"]
        # explain_finding does NOT mutate finding status
        return self._response, finding.status or "active", finding


async def test_explain_finding_returns_response_text():
    """explain_finding returns the LLM response text as a plain string."""
    expected = "This was flagged due to monotonous sentence rhythm."
    result = await explain_finding(
        finding_dict={
            "number": 1,
            "severity": "major",
            "lens": "prose",
            "location": "Paragraph 1",
            "evidence": "Repeated sentence starts",
            "impact": "Monotony",
            "options": ["Vary openings"],
            "flagged_by": ["prose"],
        },
        scene_text="She walked. She talked. She stopped.",
        client=object(),
        model="mock-model",
        discussion_engine=_FakeExplainPort(expected),
    )
    assert result == expected


async def test_explain_finding_uses_fixed_explain_prompt():
    """explain_finding passes the canonical explain prompt to the discussion engine."""
    captured: dict = {}

    class _CapturingPort:
        async def discuss(self, **kwargs):
            captured.update(kwargs)
            finding = kwargs["finding"]
            return "Captured.", finding.status or "active", finding

    await explain_finding(
        finding_dict={
            "number": 2,
            "severity": "minor",
            "lens": "clarity",
            "location": "L1",
            "evidence": "Unclear referent",
            "impact": "Confusion",
            "options": [],
            "flagged_by": ["clarity"],
        },
        scene_text="It was raining.",
        client=object(),
        model="test",
        discussion_engine=_CapturingPort(),
    )
    # The fixed explain prompt must contain the word "explain"
    assert "explain" in captured.get("author_message", "").lower()


async def test_explain_finding_does_not_mutate_status():
    """explain_finding does not change the finding status (read-only)."""
    original_status = "active"
    final_status_seen: list[str] = []

    class _StatusCheckPort:
        async def discuss(self, **kwargs):
            finding: CoreFinding = kwargs["finding"]
            # Status should be unchanged before the engine is called
            final_status_seen.append(finding.status or "active")
            return "Explanation.", finding.status or "active", finding

    await explain_finding(
        finding_dict={
            "number": 3,
            "severity": "critical",
            "lens": "structure",
            "location": "L10",
            "evidence": "Missing goal",
            "impact": "Weak structure",
            "options": [],
            "flagged_by": ["structure"],
            "status": original_status,
        },
        scene_text="Scene text.",
        client=object(),
        model="test",
        discussion_engine=_StatusCheckPort(),
    )
    assert final_status_seen == [original_status]


async def test_re_evaluate_uses_injected_re_eval_port():
    req = ReEvaluateFindingRequest(
        stale_finding=FindingContract(
            number=2,
            severity="minor",
            lens="clarity",
            location="Paragraph 2",
            evidence="Unclear referent",
            impact="Reader uncertainty",
            options=["Name character"],
            flagged_by=["clarity"],
            stale=True,
        ),
        updated_scene_text="Updated",
        model_settings=AnalyzeModelConfig(
            analysis_model="claude-sonnet-4-5-20250929",
            api_keys={},
            max_tokens=256,
        ),
    )

    res = await re_evaluate(req, client=object(), re_evaluation_engine=_FakeReEvalPort())

    assert res.status == "withdrawn"
    assert res.reason == "No longer applies."
