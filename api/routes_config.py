"""
Config and repo-preflight routes.
"""

import os

from fastapi import APIRouter, HTTPException

from orchestrator.repo_preflight import MARKER_FILENAME, validate_repo_path
from orchestrator.user_config import (
    DEFAULT_SCENE_EXTENSIONS,
    DEFAULT_SCENE_FOLDER,
    get_model_slots,
    get_scene_discovery_settings,
    set_model_slots,
    set_repo_path,
    set_scene_discovery_settings,
)
from orchestrator.runtime.model_slots import (
    default_model_slots,
    validate_model_slots,
)
from orchestrator.services.analysis_service import (
    API_KEY_ENV_VARS,
    DEFAULT_MODEL,
    get_available_models,
    model_registry_status,
)
from .route_helpers import MODE_COST_HINTS, _debug_scenes_trace, _repo_preflight_payload
from .schemas import ModelSlotsUpdateRequest, RepoPathUpdateRequest, SceneDiscoveryConfigUpdateRequest

router = APIRouter()


@router.get("/config")
async def get_config():
    """Return non-secret configuration state for the frontend."""
    models = get_available_models()
    scene_folder, scene_extensions = get_scene_discovery_settings()

    # Report which providers have API keys configured
    api_keys_configured = {
        provider: bool(os.environ.get(env_var))
        for provider, env_var in API_KEY_ENV_VARS.items()
    }

    return {
        "api_key_configured": any(api_keys_configured.values()),
        "api_keys_configured": api_keys_configured,
        "available_models": {
            name: {
                "label": cfg["label"],
                "provider": cfg["provider"],
                "id": cfg["id"],
                "max_tokens": cfg["max_tokens"],
            }
            for name, cfg in models.items()
        },
        "default_model": DEFAULT_MODEL,
        "model_registry": model_registry_status(),
        "analysis_modes": ["quick", "deep"],
        "default_analysis_mode": "deep",
        "mode_cost_hints": MODE_COST_HINTS,
        "model_slots": get_model_slots() or default_model_slots(),
        "default_model_slots": default_model_slots(),
        "scene_folder": scene_folder,
        "scene_extensions": list(scene_extensions),
        "default_scene_folder": DEFAULT_SCENE_FOLDER,
        "default_scene_extensions": list(DEFAULT_SCENE_EXTENSIONS),
    }


@router.post("/config")
async def update_config(req: SceneDiscoveryConfigUpdateRequest):
    """Update persisted scene discovery configuration."""
    set_scene_discovery_settings(req.scene_folder, req.scene_extensions)
    scene_folder, scene_extensions = get_scene_discovery_settings()
    _debug_scenes_trace(
        "POST /api/config",
        requested_scene_folder=req.scene_folder,
        requested_scene_extensions=req.scene_extensions,
        persisted_scene_folder=scene_folder,
        persisted_scene_extensions=list(scene_extensions),
    )
    return {
        "scene_folder": scene_folder,
        "scene_extensions": list(scene_extensions),
        "default_scene_folder": DEFAULT_SCENE_FOLDER,
        "default_scene_extensions": list(DEFAULT_SCENE_EXTENSIONS),
    }


@router.get("/config/models")
async def get_config_models():
    """Return model-slot configuration and available models."""
    models = get_available_models()
    configured_slots = get_model_slots() or {}
    slots = default_model_slots()
    slots.update(configured_slots)

    return {
        "model_slots": slots,
        "default_model_slots": default_model_slots(),
        "available_models": {
            name: {
                "label": cfg["label"],
                "provider": cfg["provider"],
                "id": cfg["id"],
                "max_tokens": cfg["max_tokens"],
            }
            for name, cfg in models.items()
        },
        "analysis_modes": ["quick", "deep"],
        "default_analysis_mode": "deep",
    }


@router.post("/config/models")
async def update_config_models(req: ModelSlotsUpdateRequest):
    """Validate and persist model-slot configuration."""
    try:
        validated_slots = validate_model_slots(
            {
                "frontier": req.frontier,
                "deep": req.deep,
                "quick": req.quick,
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    set_model_slots(validated_slots)
    return {
        "model_slots": validated_slots,
        "default_model_slots": default_model_slots(),
    }


@router.get("/repo-preflight")
async def get_repo_preflight():
    """Return preflight validation status for configured repo path."""
    return _repo_preflight_payload()


@router.post("/repo-path")
async def update_repo_path(req: RepoPathUpdateRequest):
    """Validate and persist the repo path in user-level config."""
    validation = validate_repo_path(req.repo_path)
    if not validation.ok:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "repo_path_invalid",
                "ok": validation.ok,
                "reason_code": validation.reason_code,
                "message": validation.message,
                "path": validation.path,
                "marker": MARKER_FILENAME,
            },
        )

    assert validation.path is not None
    set_repo_path(validation.path)

    return _repo_preflight_payload()
