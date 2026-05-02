"""Compatibility adapters between legacy server outputs and v1 contracts."""

from __future__ import annotations

from typing import Any

from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    DiscussAction,
    DiscussRequest,
    DiscussResponse,
    FindingContract,
    MetaContract,
    ReEvaluateFindingResponse,
)


def _index_contract_to_legacy_files(indexes: dict[str, str | None]) -> dict[str, str]:
    mapping = {
        "CANON": "CANON.md",
        "CAST": "cast",
        "GLOSSARY": "glossary",
        "STYLE": "STYLE.md",
        "THREADS": "threads",
        "TIMELINE": "timeline",
    }
    legacy: dict[str, str] = {}
    for contract_key, legacy_key in mapping.items():
        legacy[legacy_key] = indexes.get(contract_key) or ""
    return legacy


def adapt_analyze_request_to_legacy(req: AnalyzeRequest) -> dict[str, Any]:
    """Adapt a v1 analyze request into arguments expected by current services."""
    return {
        "scene": req.scene_text,
        "indexes": _index_contract_to_legacy_files(req.indexes.model_dump()),
        "model": req.model_settings.analysis_model,
        "max_tokens": req.model_settings.max_tokens,
        "learning_context": req.learning_context,
        "api_keys": req.model_settings.api_keys,
        "provider_options": req.model_settings.provider_options,
    }


def adapt_discuss_request_to_legacy(req: DiscussRequest) -> dict[str, Any]:
    """Adapt a v1 discuss request into arguments expected by current services."""
    return {
        "scene_text": req.scene_text,
        "finding": req.finding.model_dump(),
        "discussion_context": req.discussion_context,
        "author_message": req.author_message,
        "discussion_model": req.model_settings.discussion_model,
        "max_tokens": req.model_settings.max_tokens,
        "api_keys": req.model_settings.api_keys,
        "provider_options": req.model_settings.provider_options,
    }


def _finding_from_legacy(data: dict[str, Any]) -> FindingContract:
    return FindingContract.model_validate(
        {
            "number": data.get("number", 1),
            "severity": data.get("severity", "minor"),
            "lens": data.get("lens", "unknown"),
            "location": data.get("location", ""),
            "line_start": data.get("line_start"),
            "line_end": data.get("line_end"),
            "evidence": data.get("evidence", ""),
            "impact": data.get("impact", ""),
            "options": data.get("options", []),
            "flagged_by": data.get("flagged_by", []),
            "ambiguity_type": data.get("ambiguity_type"),
            "stale": data.get("stale", False),
        }
    )


def _status_to_action(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "withdrawn":
        return "withdraw"
    if s == "revised":
        return "revise"
    if s == "escalated":
        return "escalate"
    if s in {"conceded", "rejected", "accepted", "continue"}:
        return "defend"
    return "defend"


def adapt_legacy_analyze_output_to_response(
    legacy_output: dict[str, Any],
    *,
    model_used: str,
    timings: dict[str, float] | None = None,
    token_usage: dict[str, int | float] | None = None,
) -> AnalyzeResponse:
    """Adapt current run_analysis output to the v1 analyze response contract."""
    findings = [_finding_from_legacy(f) for f in legacy_output.get("findings", [])]
    return AnalyzeResponse(
        findings=findings,
        glossary_issues=legacy_output.get("glossary_issues", []),
        meta=MetaContract(model_used=model_used, timings=timings, token_usage=token_usage),
    )


def adapt_legacy_discuss_output_to_response(
    legacy_output: dict[str, Any],
    *,
    model_used: str,
    timings: dict[str, float] | None = None,
    token_usage: dict[str, int | float] | None = None,
) -> DiscussResponse:
    """Adapt current discussion output to the v1 discuss response contract."""
    status = legacy_output.get("status", "continue")
    finding_data = legacy_output.get("finding")
    updated_finding = _finding_from_legacy(finding_data) if finding_data else None

    return DiscussResponse(
        assistant_response=legacy_output.get("response", ""),
        action=DiscussAction(type=_status_to_action(status), payload={"legacy_status": status}),
        updated_finding=updated_finding,
        extracted_preference=legacy_output.get("extracted_preference"),
        meta=MetaContract(model_used=model_used, timings=timings, token_usage=token_usage),
    )


def adapt_legacy_re_evaluate_output_to_response(
    legacy_output: dict[str, Any],
    *,
    model_used: str,
    original_finding: dict[str, Any] | None = None,
    timings: dict[str, float] | None = None,
    token_usage: dict[str, int | float] | None = None,
) -> ReEvaluateFindingResponse:
    """Adapt current re-evaluation output to the v1 contract."""
    status = legacy_output.get("status")
    if status not in {"updated", "withdrawn"}:
        raise ValueError(f"Unsupported legacy re-evaluate status: {status}")

    updated_finding = None
    if status == "updated" and original_finding is not None:
        updated_finding = _finding_from_legacy(original_finding)

    return ReEvaluateFindingResponse(
        status=status,
        updated_finding=updated_finding,
        reason=legacy_output.get("reason"),
        meta=MetaContract(model_used=model_used, timings=timings, token_usage=token_usage),
    )


