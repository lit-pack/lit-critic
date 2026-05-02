"""Model-slot configuration and depth-mode resolution helpers.

Supports two calling conventions:
- Legacy depth-mode: mode = "quick" | "deep"  (resolved via configured model slots)
- Direct model:      mode = any known model name, e.g. "opus", "sonnet", "haiku"
  In this case the named model is used for all roles (checker + discussion).
"""

from __future__ import annotations

from typing import Mapping

from .config import DEFAULT_MODEL, is_known_model

SLOT_FRONTIER = "frontier"
SLOT_DEEP = "deep"
SLOT_QUICK = "quick"

ANALYSIS_MODE_QUICK = "quick"
ANALYSIS_MODE_DEEP = "deep"

VALID_ANALYSIS_MODES = {
    ANALYSIS_MODE_QUICK,
    ANALYSIS_MODE_DEEP,
}


def default_model_slots() -> dict[str, str]:
    quick_default = "haiku" if is_known_model("haiku") else DEFAULT_MODEL
    return {
        SLOT_FRONTIER: DEFAULT_MODEL,
        SLOT_DEEP: DEFAULT_MODEL,
        SLOT_QUICK: quick_default,
    }


def normalize_model_slots(raw: Mapping[str, str] | None) -> dict[str, str]:
    slots = default_model_slots()
    if not raw:
        return slots

    for key in (SLOT_FRONTIER, SLOT_DEEP, SLOT_QUICK):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            slots[key] = value.strip()
    return slots


def validate_model_slots(slots: Mapping[str, str]) -> dict[str, str]:
    normalized = normalize_model_slots(slots)
    for key, value in normalized.items():
        if not is_known_model(value):
            raise ValueError(f"Unknown model '{value}' for slot '{key}'")
    return normalized


def resolve_models_for_mode(mode: str, slots: Mapping[str, str] | None) -> dict[str, str]:
    resolved_mode = (mode or ANALYSIS_MODE_DEEP).strip().lower()

    # Direct model name: skip slot lookup entirely — the named model fills all roles.
    if resolved_mode not in VALID_ANALYSIS_MODES:
        if not is_known_model(resolved_mode):
            raise ValueError(
                f"mode must be one of: quick, deep — or a known model name such as opus, sonnet, haiku"
            )
        return {
            "mode": ANALYSIS_MODE_DEEP,
            "frontier_model": resolved_mode,
            "checker_model": resolved_mode,
            "analysis_model": resolved_mode,
            "discussion_model": resolved_mode,
        }

    normalized_slots = validate_model_slots(normalize_model_slots(slots))
    frontier_model = normalized_slots[SLOT_FRONTIER]
    checker_model = (
        normalized_slots[SLOT_QUICK]
        if resolved_mode == ANALYSIS_MODE_QUICK
        else normalized_slots[SLOT_DEEP]
    )

    return {
        "mode": resolved_mode,
        "frontier_model": frontier_model,
        "checker_model": checker_model,
        "analysis_model": checker_model,
        "discussion_model": frontier_model,
    }
