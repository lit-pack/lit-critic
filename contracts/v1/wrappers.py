"""Compatibility wrapper functions that preserve current behavior."""

from __future__ import annotations

from typing import Any

from orchestrator.runtime.api import run_analysis
from orchestrator.runtime.llm.base import LLMClient

from .adapters import (
    adapt_analyze_request_to_legacy,
    adapt_legacy_analyze_output_to_response,
    adapt_legacy_discuss_output_to_response,
    adapt_legacy_re_evaluate_output_to_response,
)
from .schemas import AnalyzeRequest, AnalyzeResponse, DiscussResponse, ReEvaluateFindingResponse


async def run_analyze_contract_compatible(
    client: LLMClient,
    request: AnalyzeRequest,
) -> AnalyzeResponse:
    """Run legacy analysis flow while serving the v1 contract response shape."""
    legacy_request = adapt_analyze_request_to_legacy(request)
    legacy_output = await run_analysis(
        client,
        legacy_request["scene"],
        legacy_request["indexes"],
        model=legacy_request["model"],
        max_tokens=legacy_request["max_tokens"],
    )
    return adapt_legacy_analyze_output_to_response(
        legacy_output,
        model_used=legacy_request["model"],
    )


def to_discuss_contract_response(
    legacy_output: dict[str, Any],
    *,
    model_used: str,
) -> DiscussResponse:
    """Convert existing discussion output into the v1 response contract."""
    return adapt_legacy_discuss_output_to_response(
        legacy_output,
        model_used=model_used,
    )


def to_re_evaluate_contract_response(
    legacy_output: dict[str, Any],
    *,
    model_used: str,
    original_finding: dict[str, Any] | None = None,
) -> ReEvaluateFindingResponse:
    """Convert existing re-evaluate output into the v1 response contract."""
    return adapt_legacy_re_evaluate_output_to_response(
        legacy_output,
        model_used=model_used,
        original_finding=original_finding,
    )
