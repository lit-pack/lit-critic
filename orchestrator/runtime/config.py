"""
Configuration constants for the lit-critic system.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any

# Available models with their API identifiers, provider, and token limits
BASE_AVAILABLE_MODELS = {
    # --- Anthropic / Claude ---
    "opus":     {"id": "claude-opus-4-6",            "provider": "anthropic", "max_tokens": 8192, "label": "Opus 4.6 (deepest analysis)"},
    "opus-4-5": {"id": "claude-opus-4-5-20251101",   "provider": "anthropic", "max_tokens": 8192, "label": "Opus 4.5"},
    "sonnet":   {"id": "claude-sonnet-4-5-20250929",  "provider": "anthropic", "max_tokens": 4096, "label": "Sonnet 4.5 (balanced)"},
    "haiku":    {"id": "claude-haiku-4-5-20251001",   "provider": "anthropic", "max_tokens": 4096, "label": "Haiku 4.5 (fast & cheap)"},
    # --- OpenAI ---
    "gpt-4o":      {"id": "gpt-4o",      "provider": "openai", "max_tokens": 4096, "label": "GPT-4o (balanced)"},
    "gpt-4o-mini": {"id": "gpt-4o-mini", "provider": "openai", "max_tokens": 4096, "label": "GPT-4o Mini (fast & cheap)"},
    "o3":          {"id": "o3",           "provider": "openai", "max_tokens": 8192, "label": "o3 (reasoning)"},
}

# Mutable map used by the rest of the system. Starts from curated baseline,
# then optionally gets enriched by auto-discovery.
AVAILABLE_MODELS = {k: dict(v) for k, v in BASE_AVAILABLE_MODELS.items()}

DEFAULT_MODEL = "sonnet"

# Discussion model — None means "use the analysis model"
# Can be set to any key from AVAILABLE_MODELS for a separate discussion model
DEFAULT_DISCUSSION_MODEL = None

# Backward-compatible constants (resolve from default)
MODEL = AVAILABLE_MODELS[DEFAULT_MODEL]["id"]
MAX_TOKENS = AVAILABLE_MODELS[DEFAULT_MODEL]["max_tokens"]

# The coordinator merges findings from all 6 lenses into a single structured
# JSON.  Its output is typically much larger than an individual lens response,
# so it gets a dedicated (generous) token budget.  16 384 tokens can hold
# ~50-60 findings — more than any realistic scene review should produce.
COORDINATOR_MAX_TOKENS = 16_384

# Environment variable names for API keys, keyed by provider
API_KEY_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
}


_MODEL_DISCOVERY_ENABLED_ENV = "LIT_CRITIC_MODEL_DISCOVERY_ENABLED"
_MODEL_DISCOVERY_TTL_SECONDS_ENV = "LIT_CRITIC_MODEL_DISCOVERY_TTL_SECONDS"
_MODEL_DISCOVERY_TIMEOUT_SECONDS_ENV = "LIT_CRITIC_MODEL_DISCOVERY_TIMEOUT_SECONDS"
_MODEL_CACHE_PATH_ENV = "LIT_CRITIC_MODEL_CACHE_PATH"

_DEFAULT_DISCOVERY_TTL_SECONDS = 24 * 60 * 60
_DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 8

_MODEL_CACHE_PATH = Path(
    os.environ.get(
        _MODEL_CACHE_PATH_ENV,
        str(Path.home() / ".lit-critic-models-cache.json"),
    )
)

_cache_loaded = False
_last_refresh_attempt_at: float | None = None
_last_refresh_success_at: float | None = None


def _to_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _auto_discovery_enabled() -> bool:
    # Keep tests deterministic and offline by default.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False

    raw = os.environ.get(_MODEL_DISCOVERY_ENABLED_ENV, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _discovery_ttl_seconds() -> int:
    return _to_int_env(_MODEL_DISCOVERY_TTL_SECONDS_ENV, _DEFAULT_DISCOVERY_TTL_SECONDS)


def _discovery_timeout_seconds() -> int:
    return _to_int_env(_MODEL_DISCOVERY_TIMEOUT_SECONDS_ENV, _DEFAULT_DISCOVERY_TIMEOUT_SECONDS)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-")


def _is_openai_text_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return bool(
        lowered.startswith("gpt-")
        or re.match(r"^o\d", lowered)
        or lowered.startswith("chatgpt-")
    )


def _anthropic_key_from_id(model_id: str) -> str:
    lowered = model_id.lower()
    if lowered.startswith("claude-"):
        lowered = lowered[len("claude-"):]
    return _slug(lowered)


def _openai_key_from_id(model_id: str) -> str:
    return _slug(model_id)


def _format_label(model_id: str, provider: str) -> str:
    source = "Anthropic" if provider == "anthropic" else "OpenAI"
    return f"{model_id} ({source}, auto-discovered)"


def _discover_openai_models(api_key: str) -> dict[str, dict[str, Any]]:
    try:
        from openai import OpenAI
    except Exception:
        return {}

    try:
        client = OpenAI(api_key=api_key, timeout=_discovery_timeout_seconds())
        payload = client.models.list()
    except Exception:
        return {}

    data = getattr(payload, "data", payload)
    discovered: dict[str, dict[str, Any]] = {}

    for item in data or []:
        model_id = getattr(item, "id", None)
        if not model_id and isinstance(item, dict):
            model_id = item.get("id")
        if not model_id or not _is_openai_text_model(str(model_id)):
            continue

        model_id = str(model_id)
        key = _openai_key_from_id(model_id)
        discovered[key] = {
            "id": model_id,
            "provider": "openai",
            "max_tokens": 4096,
            "label": _format_label(model_id, "openai"),
        }

    return discovered


def _discover_anthropic_models(api_key: str) -> dict[str, dict[str, Any]]:
    try:
        from anthropic import Anthropic
    except Exception:
        return {}

    try:
        client = Anthropic(api_key=api_key, timeout=_discovery_timeout_seconds())
        payload = client.models.list()
    except Exception:
        return {}

    data = getattr(payload, "data", payload)
    discovered: dict[str, dict[str, Any]] = {}

    for item in data or []:
        model_id = getattr(item, "id", None)
        if not model_id and isinstance(item, dict):
            model_id = item.get("id")
        if not model_id:
            continue

        model_id = str(model_id)
        if not model_id.lower().startswith("claude-"):
            continue

        key = _anthropic_key_from_id(model_id)
        discovered[key] = {
            "id": model_id,
            "provider": "anthropic",
            "max_tokens": 4096,
            "label": _format_label(model_id, "anthropic"),
        }

    return discovered


def _read_model_cache() -> tuple[dict[str, dict[str, Any]], float | None]:
    if not _MODEL_CACHE_PATH.exists():
        return {}, None

    try:
        payload = json.loads(_MODEL_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}, None

    raw_models = payload.get("models")
    if not isinstance(raw_models, dict):
        return {}, None

    loaded: dict[str, dict[str, Any]] = {}
    for key, cfg in raw_models.items():
        if not isinstance(cfg, dict):
            continue
        if not all(k in cfg for k in ("id", "provider", "max_tokens", "label")):
            continue
        loaded[str(key)] = {
            "id": str(cfg["id"]),
            "provider": str(cfg["provider"]),
            "max_tokens": int(cfg["max_tokens"]),
            "label": str(cfg["label"]),
        }

    timestamp = payload.get("updated_at")
    updated_at = float(timestamp) if isinstance(timestamp, (int, float)) else None
    return loaded, updated_at


def _write_model_cache(models: dict[str, dict[str, Any]], updated_at: float) -> None:
    try:
        _MODEL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": updated_at,
            "models": models,
        }
        _MODEL_CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        # Cache persistence should never break runtime behaviour.
        return


def _merge_models(models: dict[str, dict[str, Any]]) -> None:
    if not models:
        return
    AVAILABLE_MODELS.update(models)


def _load_cached_models_once() -> None:
    global _cache_loaded, _last_refresh_success_at

    if _cache_loaded:
        return

    cached_models, updated_at = _read_model_cache()
    _merge_models(cached_models)
    _cache_loaded = True
    if updated_at is not None:
        _last_refresh_success_at = updated_at


def refresh_available_models(force: bool = False) -> dict[str, dict[str, Any]]:
    """Refresh AVAILABLE_MODELS from provider APIs when possible.

    Strategy:
    - Start with curated baseline.
    - Merge cached discovered models (if any).
    - Optionally re-discover from provider APIs based on TTL/flags.
    - On any failure, keep serving existing models.
    """
    global _last_refresh_attempt_at, _last_refresh_success_at

    _load_cached_models_once()

    if not _auto_discovery_enabled():
        return AVAILABLE_MODELS

    now = time.time()
    if not force:
        ttl = _discovery_ttl_seconds()
        if _last_refresh_attempt_at is not None and (now - _last_refresh_attempt_at) < ttl:
            return AVAILABLE_MODELS

    _last_refresh_attempt_at = now

    discovered: dict[str, dict[str, Any]] = {}

    openai_key = os.environ.get(API_KEY_ENV_VARS["openai"], "").strip()
    if openai_key:
        discovered.update(_discover_openai_models(openai_key))

    anthropic_key = os.environ.get(API_KEY_ENV_VARS["anthropic"], "").strip()
    if anthropic_key:
        discovered.update(_discover_anthropic_models(anthropic_key))

    if discovered:
        _merge_models(discovered)
        _write_model_cache(discovered, now)
        _last_refresh_success_at = now

    return AVAILABLE_MODELS


def get_available_models(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Return currently available model map, optionally forcing refresh."""
    models = refresh_available_models(force=force_refresh)
    return {name: dict(cfg) for name, cfg in models.items()}


def is_known_model(name: str) -> bool:
    """Return True if model short name is currently known."""
    return name in get_available_models()


def model_registry_status() -> dict[str, Any]:
    """Return non-secret status metadata for diagnostics/UI."""
    _load_cached_models_once()
    return {
        "auto_discovery_enabled": _auto_discovery_enabled(),
        "cache_path": str(_MODEL_CACHE_PATH),
        "ttl_seconds": _discovery_ttl_seconds(),
        "last_refresh_attempt_at": _last_refresh_attempt_at,
        "last_refresh_success_at": _last_refresh_success_at,
    }


def resolve_model(name: str) -> dict:
    """Resolve a model short name to its config dict.
    
    Returns dict with keys: id, provider, max_tokens, label
    Raises ValueError if name is not recognised.
    """
    models = get_available_models()
    if name not in models:
        valid = ", ".join(models.keys())
        raise ValueError(f"Unknown model '{name}'. Available models: {valid}")
    return models[name]


def resolve_api_key(provider: str, explicit_key: str | None = None) -> str:
    """Get the API key for a provider.

    Priority:
        1. ``explicit_key`` if provided (e.g. from CLI ``--api-key`` or request body).
        2. The provider's environment variable (``ANTHROPIC_API_KEY`` or ``OPENAI_API_KEY``).

    Raises ValueError if no key is found.
    """
    if explicit_key:
        return explicit_key

    env_var = API_KEY_ENV_VARS.get(provider)
    if env_var:
        key = os.environ.get(env_var)
        if key:
            return key

    raise ValueError(
        f"No API key for provider '{provider}'. "
        f"Pass --api-key or set the {API_KEY_ENV_VARS.get(provider, '???')} environment variable."
    )


INDEX_FILES = [
    "CANON.md",
    "STYLE.md",
]

OPTIONAL_FILES = []

CONTEXT_FILES = INDEX_FILES + OPTIONAL_FILES

SESSION_FILE = ".lit-critic-session.json"  # Legacy — kept for reference only
DB_FILE = ".lit-critic.db"
