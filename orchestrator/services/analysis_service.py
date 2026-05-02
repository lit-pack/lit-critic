"""Platform-facing analysis orchestration bridge.

This module provides a Platform import surface for analysis-related workflow
operations while legacy runtime pieces are still being phased out.
"""

from orchestrator.runtime.api import run_analysis, run_coordinator, run_coordinator_chunked, run_lens
from orchestrator.runtime.config import (
    API_KEY_ENV_VARS,
    AVAILABLE_MODELS,
    BASE_AVAILABLE_MODELS,
    COORDINATOR_MAX_TOKENS,
    DEFAULT_MODEL,
    INDEX_FILES,
    MAX_TOKENS,
    MODEL,
    OPTIONAL_FILES,
    get_available_models,
    is_known_model,
    model_registry_status,
    refresh_available_models,
    resolve_api_key,
    resolve_model,
)
from orchestrator.runtime.llm import create_client

__all__ = [
    "INDEX_FILES",
    "OPTIONAL_FILES",
    "AVAILABLE_MODELS",
    "BASE_AVAILABLE_MODELS",
    "DEFAULT_MODEL",
    "API_KEY_ENV_VARS",
    "MODEL",
    "MAX_TOKENS",
    "COORDINATOR_MAX_TOKENS",
    "get_available_models",
    "refresh_available_models",
    "is_known_model",
    "model_registry_status",
    "resolve_model",
    "resolve_api_key",
    "create_client",
    "run_lens",
    "run_coordinator",
    "run_coordinator_chunked",
    "run_analysis",
]
