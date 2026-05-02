"""User-level configuration persistence for lit-critic clients."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


_VALID_REVIEW_PASS_VALUES = frozenset({"always", "on_stale", "never"})
_DEFAULT_REVIEW_PASS = "always"


@dataclass
class UserConfig:
    repo_path: str | None = None
    model_slots: dict[str, str] | None = None
    scene_folder: str | None = None
    scene_extensions: tuple[str, ...] | None = None
    knowledge_review_pass: str = _DEFAULT_REVIEW_PASS


DEFAULT_SCENE_FOLDER = "text"
DEFAULT_SCENE_EXTENSIONS = ("txt",)


def _extract_legacy_model_slots(data: dict) -> dict[str, str] | None:
    """Map legacy model preferences to slot-first configuration.

    Legacy keys (if present in older config files):
      - analysis_model
      - discussion_model

    Migration strategy (Phase 2): both legacy values map to ``frontier``.
    If both are present and differ, ``analysis_model`` wins.
    """
    if not isinstance(data, dict):
        return None

    analysis_model = data.get("analysis_model")
    discussion_model = data.get("discussion_model")

    frontier = None
    if isinstance(analysis_model, str) and analysis_model.strip():
        frontier = analysis_model.strip()
    elif isinstance(discussion_model, str) and discussion_model.strip():
        frontier = discussion_model.strip()

    if not frontier:
        return None

    return {"frontier": frontier}


def get_user_config_path() -> Path:
    """Return the user-level config file path.

    Uses a platform-appropriate location and supports an override via
    ``LIT_CRITIC_USER_CONFIG_PATH`` for tests.
    """
    override = os.environ.get("LIT_CRITIC_USER_CONFIG_PATH", "").strip()
    if override:
        return Path(override)

    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            base = Path(appdata)
        else:
            # Some tests clear all env vars; avoid relying on Path.home() in that case.
            userprofile = os.environ.get("USERPROFILE", "").strip()
            if userprofile:
                base = Path(userprofile) / "AppData" / "Roaming"
            else:
                homedrive = os.environ.get("HOMEDRIVE", "").strip()
                homepath = os.environ.get("HOMEPATH", "").strip()
                if homedrive and homepath:
                    base = Path(f"{homedrive}{homepath}") / "AppData" / "Roaming"
                else:
                    # Last-resort fallback for heavily sandboxed test environments.
                    base = Path.cwd() / ".lit-critic-user"

        return base / "lit-critic" / "config.json"

    return Path.home() / ".config" / "lit-critic" / "config.json"


def load_user_config() -> UserConfig:
    path = get_user_config_path()
    if not path.exists():
        return UserConfig()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return UserConfig()

    repo_path = data.get("repo_path") if isinstance(data, dict) else None
    if isinstance(repo_path, str):
        repo_path = repo_path.strip() or None
    else:
        repo_path = None
    model_slots = data.get("model_slots") if isinstance(data, dict) else None
    if isinstance(model_slots, dict):
        model_slots = dict(model_slots)
    else:
        model_slots = _extract_legacy_model_slots(data if isinstance(data, dict) else {})

    scene_folder = data.get("scene_folder") if isinstance(data, dict) else None
    if isinstance(scene_folder, str):
        scene_folder = scene_folder.strip() or None
    else:
        scene_folder = None

    raw_scene_extensions = data.get("scene_extensions") if isinstance(data, dict) else None
    scene_extensions: tuple[str, ...] | None = None
    if isinstance(raw_scene_extensions, list):
        normalized = []
        for ext in raw_scene_extensions:
            if not isinstance(ext, str):
                continue
            cleaned = ext.strip().lower().lstrip(".")
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        if normalized:
            scene_extensions = tuple(normalized)

    raw_review_pass = data.get("knowledge_review_pass") if isinstance(data, dict) else None
    knowledge_review_pass = (
        raw_review_pass
        if isinstance(raw_review_pass, str) and raw_review_pass in _VALID_REVIEW_PASS_VALUES
        else _DEFAULT_REVIEW_PASS
    )

    return UserConfig(
        repo_path=repo_path,
        model_slots=model_slots,
        scene_folder=scene_folder,
        scene_extensions=scene_extensions,
        knowledge_review_pass=knowledge_review_pass,
    )


def save_user_config(config: UserConfig) -> None:
    path = get_user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "repo_path": config.repo_path,
        "model_slots": config.model_slots or None,
        "scene_folder": config.scene_folder,
        "scene_extensions": list(config.scene_extensions) if config.scene_extensions else None,
        "knowledge_review_pass": config.knowledge_review_pass,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_repo_path() -> str | None:
    return load_user_config().repo_path


def set_repo_path(repo_path: str) -> None:
    existing = load_user_config()
    save_user_config(
        UserConfig(
            repo_path=repo_path.strip() or None,
            model_slots=existing.model_slots,
            scene_folder=existing.scene_folder,
            scene_extensions=existing.scene_extensions,
        )
    )


def get_model_slots() -> dict[str, str] | None:
    model_slots = load_user_config().model_slots
    return dict(model_slots) if isinstance(model_slots, dict) else None


def set_model_slots(model_slots: dict[str, str]) -> None:
    existing = load_user_config()
    save_user_config(
        UserConfig(
            repo_path=existing.repo_path,
            model_slots=dict(model_slots),
            scene_folder=existing.scene_folder,
            scene_extensions=existing.scene_extensions,
        )
    )


def get_scene_discovery_settings() -> tuple[str, tuple[str, ...]]:
    config = load_user_config()
    scene_folder = config.scene_folder or DEFAULT_SCENE_FOLDER
    scene_extensions = config.scene_extensions or DEFAULT_SCENE_EXTENSIONS
    return scene_folder, scene_extensions


def set_scene_discovery_settings(scene_folder: str, scene_extensions: list[str]) -> None:
    existing = load_user_config()

    normalized_folder = scene_folder.strip() or DEFAULT_SCENE_FOLDER
    normalized_extensions: list[str] = []
    for ext in scene_extensions:
        cleaned = ext.strip().lower().lstrip(".")
        if cleaned and cleaned not in normalized_extensions:
            normalized_extensions.append(cleaned)
    if not normalized_extensions:
        normalized_extensions = list(DEFAULT_SCENE_EXTENSIONS)

    save_user_config(
        UserConfig(
            repo_path=existing.repo_path,
            model_slots=existing.model_slots,
            scene_folder=normalized_folder,
            scene_extensions=tuple(normalized_extensions),
        )
    )


def get_knowledge_review_pass_setting() -> str:
    """Return the current knowledge review pass trigger setting."""
    return load_user_config().knowledge_review_pass


def set_knowledge_review_pass_setting(value: str) -> None:
    """Persist the knowledge review pass trigger setting."""
    if value not in _VALID_REVIEW_PASS_VALUES:
        raise ValueError(
            f"Invalid knowledge_review_pass value '{value}'. "
            f"Must be one of: {sorted(_VALID_REVIEW_PASS_VALUES)}"
        )
    existing = load_user_config()
    save_user_config(
        UserConfig(
            repo_path=existing.repo_path,
            model_slots=existing.model_slots,
            scene_folder=existing.scene_folder,
            scene_extensions=existing.scene_extensions,
            knowledge_review_pass=value,
        )
    )
