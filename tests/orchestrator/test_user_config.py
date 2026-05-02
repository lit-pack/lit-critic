"""Tests for user config model slot migration behavior."""

from __future__ import annotations

import json

from orchestrator.user_config import load_user_config


def _write_config(path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_user_config_migrates_legacy_analysis_model_to_frontier(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))
    _write_config(config_path, {"analysis_model": "claude-3-7-sonnet"})

    cfg = load_user_config()

    assert cfg.model_slots == {"frontier": "claude-3-7-sonnet"}


def test_load_user_config_uses_legacy_discussion_model_when_analysis_missing(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))
    _write_config(config_path, {"discussion_model": "claude-3-5-haiku"})

    cfg = load_user_config()

    assert cfg.model_slots == {"frontier": "claude-3-5-haiku"}


def test_load_user_config_legacy_analysis_wins_when_both_present(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))
    _write_config(
        config_path,
        {
            "analysis_model": "claude-3-7-sonnet",
            "discussion_model": "claude-3-5-haiku",
        },
    )

    cfg = load_user_config()

    assert cfg.model_slots == {"frontier": "claude-3-7-sonnet"}


def test_load_user_config_prefers_model_slots_over_legacy_keys(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("LIT_CRITIC_USER_CONFIG_PATH", str(config_path))
    _write_config(
        config_path,
        {
            "model_slots": {"frontier": "slot-model"},
            "analysis_model": "legacy-model",
        },
    )

    cfg = load_user_config()

    assert cfg.model_slots == {"frontier": "slot-model"}
