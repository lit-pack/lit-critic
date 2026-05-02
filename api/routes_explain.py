"""
Explain API endpoint — one-shot LLM explanation for a finding.

POST /api/findings/{finding_id}/explain

The client passes the finding object and relevant scene text.
The server performs a single LLM query and returns the explanation.
No state change, no discussion history, no learning signal.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import core.service as core_service
from orchestrator.runtime.config import resolve_api_key, resolve_model
from orchestrator.runtime.llm.factory import create_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/findings", tags=["explain"])

# Explanation depth → model slot alias.
# "quick" → cheap fast model (haiku-tier).
# "deep"  → frontier model for nuanced literary judgment.
_DEPTH_TO_SLOT: dict[str, str] = {
    "quick": "quick",
    "deep": "frontier",
}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ExplainRequest(BaseModel):
    """Body for POST /api/findings/{finding_id}/explain."""

    depth: Literal["quick", "deep"] = "quick"
    """Explanation depth. 'quick' is the default one-click option (cheap + fast).
    'deep' uses the frontier model for complex literary judgments."""

    finding: dict[str, Any]
    """Full finding object as returned by the analysis API.
    The client already has this data; passing it avoids a round-trip DB lookup."""

    scene_text: str
    """The relevant scene text for LLM context (the full scene or the relevant excerpt)."""

    model: Optional[str] = None
    """Optional model name override. Defaults to the configured slot for the given depth."""

    max_tokens: int = 1024
    """Token budget for the explanation. Explanations are brief — 1 K is generous."""


class ExplainResponse(BaseModel):
    finding_id: int
    depth: str
    explanation: str
    model_used: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_model_name(depth: str, override: str | None) -> str:
    """Select the model name to use for the given explanation depth.

    Tries the depth slot alias first (e.g. "quick", "frontier"), falls back to
    "claude-haiku" / "claude-3-5-sonnet" if the slot is not configured.
    """
    if override:
        return override

    slot = _DEPTH_TO_SLOT.get(depth, "quick")
    try:
        cfg = resolve_model(slot)
        return cfg["id"]
    except (ValueError, KeyError):
        pass

    # Hard-coded fallbacks — resolve_model will raise if neither is configured
    fallback = "claude-haiku" if depth == "quick" else "claude-3-5-sonnet"
    return fallback


def _build_client(model_name: str):
    """Resolve provider config and create an LLM client for the given model."""
    try:
        cfg = resolve_model(model_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    provider = cfg["provider"]
    try:
        api_key = resolve_api_key(provider, None)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"No API key configured for provider '{provider}': {exc}",
        ) from exc

    try:
        client = create_client(provider, api_key)
    except (ValueError, ImportError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return client, cfg["id"]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/{finding_id}/explain", response_model=ExplainResponse)
async def explain_finding(
    finding_id: int,
    body: ExplainRequest,
    project_path: str = Query(..., description="Absolute path to the project directory"),
) -> ExplainResponse:
    """Generate a one-shot explanation for a finding.

    The client sends the finding object and the relevant scene text.
    The server performs a single LLM query (using the quick or frontier model
    depending on ``depth``) and returns the explanation text.

    No state is modified; no learning signal is generated.
    Cost is reported in the response so the UI can update the budget display.
    """
    model_name = _resolve_model_name(body.depth, body.model)
    client, model_id = _build_client(model_name)

    try:
        explanation = await core_service.explain_finding(
            finding_dict=body.finding,
            scene_text=body.scene_text,
            client=client,
            model=model_id,
            max_tokens=body.max_tokens,
        )
    except Exception as exc:
        logger.exception("explain_finding failed for finding_id=%d", finding_id)
        raise HTTPException(
            status_code=500,
            detail=f"Explanation generation failed: {exc}",
        ) from exc

    return ExplainResponse(
        finding_id=finding_id,
        depth=body.depth,
        explanation=explanation,
        model_used=model_id,
    )
