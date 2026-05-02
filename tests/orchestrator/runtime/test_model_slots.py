"""Unit tests for orchestrator.runtime.model_slots — direct model-name mode."""

import pytest

from orchestrator.runtime.model_slots import resolve_models_for_mode, ANALYSIS_MODE_DEEP


class TestResolveModelsForModeDirectModelName:
    """Verify that a known model name bypasses slot lookup and fills all roles."""

    def test_sonnet_direct_uses_sonnet_for_all_roles(self):
        result = resolve_models_for_mode("sonnet", None)
        assert result["analysis_model"] == "sonnet"
        assert result["checker_model"] == "sonnet"
        assert result["frontier_model"] == "sonnet"
        assert result["discussion_model"] == "sonnet"

    def test_opus_direct_uses_opus_for_all_roles(self):
        result = resolve_models_for_mode("opus", None)
        assert result["analysis_model"] == "opus"
        assert result["checker_model"] == "opus"
        assert result["frontier_model"] == "opus"
        assert result["discussion_model"] == "opus"

    def test_haiku_direct_uses_haiku_for_all_roles(self):
        result = resolve_models_for_mode("haiku", None)
        assert result["analysis_model"] == "haiku"
        assert result["checker_model"] == "haiku"
        assert result["frontier_model"] == "haiku"
        assert result["discussion_model"] == "haiku"

    def test_direct_model_name_reports_mode_as_deep(self):
        """Stored depth_mode should always be 'deep' when a model name is used directly."""
        result = resolve_models_for_mode("sonnet", None)
        assert result["mode"] == ANALYSIS_MODE_DEEP

    def test_direct_model_name_slots_arg_is_ignored(self):
        """Model slots should be ignored when the mode IS a model name."""
        slots = {"frontier": "opus", "deep": "opus", "quick": "opus"}
        result = resolve_models_for_mode("sonnet", slots)
        assert result["analysis_model"] == "sonnet"
        assert result["discussion_model"] == "sonnet"

    def test_unknown_value_raises_value_error(self):
        with pytest.raises(ValueError, match="known model name"):
            resolve_models_for_mode("bogus-model-xyz", None)

    def test_unknown_value_raises_for_near_match(self):
        with pytest.raises(ValueError):
            resolve_models_for_mode("ultra", None)


class TestResolveModelsForModeLegacyModes:
    """Verify that legacy quick/deep modes still work correctly."""

    def test_deep_mode_uses_deep_slot(self):
        slots = {"frontier": "opus", "deep": "sonnet", "quick": "haiku"}
        result = resolve_models_for_mode("deep", slots)
        assert result["analysis_model"] == "sonnet"
        assert result["discussion_model"] == "opus"
        assert result["mode"] == "deep"

    def test_quick_mode_uses_quick_slot(self):
        slots = {"frontier": "opus", "deep": "sonnet", "quick": "haiku"}
        result = resolve_models_for_mode("quick", slots)
        assert result["analysis_model"] == "haiku"
        assert result["discussion_model"] == "opus"
        assert result["mode"] == "quick"

    def test_none_mode_defaults_to_deep(self):
        result = resolve_models_for_mode(None, None)  # type: ignore[arg-type]
        assert result["mode"] == "deep"
