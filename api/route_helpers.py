"""
Shared session manager, constants, and private helpers for the lit-critic Web API.
"""

import logging
import os
from typing import Optional

from fastapi import HTTPException

from orchestrator.repo_preflight import MARKER_FILENAME, validate_repo_path
from orchestrator.user_config import get_repo_path
from orchestrator.services.analysis_service import (
    API_KEY_ENV_VARS,
    DEFAULT_MODEL,
    is_known_model,
    resolve_model,
)
from .analysis_engine import AnalysisEngine

logger = logging.getLogger(__name__)

# DEBUG_SCENES_TRACE (temporary): set to false after diagnosing startup behavior.
_DEBUG_SCENES_TRACE = False

# Single shared analysis engine (single-user local tool)
analysis_engine = AnalysisEngine()


MODE_COST_HINTS = {
    "quick": "Quick mode prioritizes lower-cost checker-tier analysis.",
    "deep": "Deep mode runs fuller checker + frontier analysis and is typically the highest-cost option.",
}


def _debug_scenes_trace(message: str, **fields) -> None:
    """Emit temporary high-signal logs for scene projection startup debugging."""
    if not _DEBUG_SCENES_TRACE:
        return
    if fields:
        payload = ", ".join(f"{key}={value!r}" for key, value in fields.items())
        logger.info("[SCENES_TRACE] %s | %s", message, payload)
        return
    logger.info("[SCENES_TRACE] %s", message)


def _ensure_finding_origin(finding_payload: dict) -> dict:
    """Ensure finding payloads always expose an explicit origin."""
    normalized = dict(finding_payload)
    if not normalized.get("origin"):
        normalized["origin"] = "legacy"
    return normalized


def _ensure_finding_origins_in_response(payload):
    """Normalize API response payloads so finding objects always include origin."""
    if not isinstance(payload, dict):
        return payload

    normalized = dict(payload)

    finding = normalized.get("finding")
    if isinstance(finding, dict):
        normalized["finding"] = _ensure_finding_origin(finding)

    findings = normalized.get("findings")
    if isinstance(findings, list):
        normalized["findings"] = [
            _ensure_finding_origin(item) if isinstance(item, dict) else item
            for item in findings
        ]

    next_payload = normalized.get("next")
    if isinstance(next_payload, dict):
        normalized["next"] = _ensure_finding_origins_in_response(next_payload)

    return normalized


def _build_tier_cost_summary(*, mode: str, checker_model: str, frontier_model: Optional[str]) -> dict:
    """Build tier-level cost metadata, including availability placeholders."""
    checker_cfg = resolve_model(checker_model)
    frontier_name = frontier_model or checker_model
    frontier_cfg = resolve_model(frontier_name)

    return {
        "mode": mode,
        "estimate_hint": MODE_COST_HINTS.get(mode, MODE_COST_HINTS["deep"]),
        "actuals_available": False,
        "checker": {
            "name": checker_model,
            "label": checker_cfg["label"],
            "provider": checker_cfg["provider"],
            "token_usage": None,
            "cost_usd": None,
        },
        "frontier": {
            "name": frontier_name,
            "label": frontier_cfg["label"],
            "provider": frontier_cfg["provider"],
            "token_usage": None,
            "cost_usd": None,
        },
        "total_cost_usd": None,
    }


def _normalise_model_name(name: Optional[str], default: str = DEFAULT_MODEL) -> str:
    """Return a valid model short name, falling back to ``default``."""
    if name and is_known_model(name):
        return name
    return default


def _normalise_optional_model_name(name: Optional[str]) -> Optional[str]:
    """Return a valid optional model short name, or ``None``."""
    if name and is_known_model(name):
        return name
    return None


def _validate_api_key_matches_provider(provider: str, key: str, key_label: str) -> None:
    """Best-effort guardrail for obvious provider/key mismatches.

    - Anthropic keys are expected to start with ``sk-ant-``.
    - OpenAI keys should *not* start with ``sk-ant-``.
    """
    trimmed = key.strip()

    if provider == "openai" and trimmed.startswith("sk-ant-"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{key_label} appears to be an Anthropic key, but the selected model uses OpenAI. "
                "Provide an OpenAI key (OPENAI_API_KEY or discussion_api_key/api_key as appropriate)."
            ),
        )

    if provider == "anthropic" and trimmed.startswith("sk-") and not trimmed.startswith("sk-ant-"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{key_label} appears to be an OpenAI key, but the selected model uses Anthropic. "
                "Provide an Anthropic key (ANTHROPIC_API_KEY or discussion_api_key/api_key as appropriate)."
            ),
        )


def _resolve_provider_api_key(provider: str, explicit_key: Optional[str], key_label: str) -> str:
    """Resolve an API key for a specific provider.

    Resolution order:
    1. Explicit key from request.
    2. Provider-specific environment variable.
    """
    if explicit_key:
        _validate_api_key_matches_provider(provider, explicit_key, key_label)
        return explicit_key

    env_var = API_KEY_ENV_VARS.get(provider)
    env_key = os.environ.get(env_var) if env_var else None
    if env_key:
        _validate_api_key_matches_provider(provider, env_key, env_var or key_label)
        return env_key

    raise HTTPException(
        status_code=400,
        detail=(
            f"No API key for provider '{provider}' ({key_label}). "
            f"Provide {key_label} in request body or set {env_var}."
        ),
    )


def _repo_preflight_payload() -> dict:
    configured = get_repo_path()
    validation = validate_repo_path(configured)
    return {
        "ok": validation.ok,
        "reason_code": validation.reason_code,
        "message": validation.message,
        "path": validation.path,
        "marker": MARKER_FILENAME,
        "configured_path": configured,
    }


def _ensure_repo_preflight_ready() -> None:
    payload = _repo_preflight_payload()
    if payload["ok"]:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": "repo_path_invalid",
            **payload,
            "next_action": "Provide a valid lit-critic installation path via POST /api/repo-path.",
        },
    )


def _resolve_analysis_and_discussion_keys(
    model: str,
    discussion_model: Optional[str],
    api_key: Optional[str],
    discussion_api_key: Optional[str],
) -> tuple[str, Optional[str]]:
    """Resolve provider-correct keys for analysis and discussion models."""
    analysis_provider = resolve_model(model)["provider"]
    analysis_key = _resolve_provider_api_key(
        analysis_provider,
        api_key,
        "api_key",
    )

    if not discussion_model:
        return analysis_key, None

    discussion_provider = resolve_model(discussion_model)["provider"]

    if discussion_provider == analysis_provider:
        # Same provider: discussion key is optional. If provided, validate and use it.
        if discussion_api_key:
            discussion_key = _resolve_provider_api_key(
                discussion_provider,
                discussion_api_key,
                "discussion_api_key",
            )
            return analysis_key, discussion_key
        return analysis_key, None

    # Cross-provider: discussion provider key must be resolved independently.
    discussion_key = _resolve_provider_api_key(
        discussion_provider,
        discussion_api_key,
        "discussion_api_key",
    )
    return analysis_key, discussion_key
