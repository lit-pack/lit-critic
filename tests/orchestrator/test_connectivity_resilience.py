"""
Tests for connectivity resilience — Tasks 8 and 9 of the connectivity-resilience plan.

Task 8: `run_lens` transient error tagging (is_transient flag on LensResult).
Task 9: `run_analysis` early-exit when all lenses fail (AllLensesFailedError).
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.runtime.api import run_lens, run_analysis, _is_transient_error
from orchestrator.runtime.models import LensResult, AllLensesFailedError
from orchestrator.runtime.llm.base import LLMResponse


# ---------------------------------------------------------------------------
# Task 8: _is_transient_error helper and run_lens is_transient tagging
# ---------------------------------------------------------------------------

class TestIsTransientError:
    """Unit tests for the _is_transient_error helper."""

    def test_httpx_timeout_exception_is_transient(self):
        exc = httpx.TimeoutException("timed out")
        assert _is_transient_error(exc) is True

    def test_httpx_connect_error_is_transient(self):
        exc = httpx.ConnectError("connection refused", request=MagicMock())
        assert _is_transient_error(exc) is True

    def test_string_timed_out_is_transient(self):
        exc = Exception("request timed out or interrupted")
        assert _is_transient_error(exc) is True

    def test_string_timed_out_substring_is_transient(self):
        exc = RuntimeError("Connection timed out after 30s")
        assert _is_transient_error(exc) is True

    def test_value_error_is_not_transient(self):
        exc = ValueError("invalid schema")
        assert _is_transient_error(exc) is False

    def test_generic_runtime_error_is_not_transient(self):
        exc = RuntimeError("something unexpected")
        assert _is_transient_error(exc) is False

    def test_anthropic_api_connection_error_is_transient(self):
        try:
            import anthropic
            exc = anthropic.APIConnectionError(request=MagicMock())
            assert _is_transient_error(exc) is True
        except ImportError:
            pytest.skip("anthropic package not installed")

    def test_openai_api_connection_error_is_transient(self):
        try:
            import openai
            exc = openai.APIConnectionError(request=MagicMock())
            assert _is_transient_error(exc) is True
        except ImportError:
            pytest.skip("openai package not installed")


class TestRunLensTransientTagging:
    """Integration tests: run_lens sets is_transient based on exception type."""

    async def test_httpx_connect_timeout_sets_is_transient_true(
        self, mock_anthropic_client, sample_indexes
    ):
        """httpx.ConnectTimeout → is_transient=True."""
        exc = httpx.ConnectTimeout("connection timed out", request=MagicMock())
        mock_anthropic_client.create_message = AsyncMock(side_effect=exc)

        result = await run_lens(mock_anthropic_client, "prose", "scene text", sample_indexes)

        assert result.error is not None
        assert result.is_transient is True

    async def test_anthropic_connection_error_sets_is_transient_true(
        self, mock_anthropic_client, sample_indexes
    ):
        """anthropic.APIConnectionError → is_transient=True."""
        try:
            import anthropic
        except ImportError:
            pytest.skip("anthropic package not installed")

        exc = anthropic.APIConnectionError(request=MagicMock())
        mock_anthropic_client.create_message = AsyncMock(side_effect=exc)

        result = await run_lens(mock_anthropic_client, "prose", "scene text", sample_indexes)

        assert result.error is not None
        assert result.is_transient is True

    async def test_value_error_sets_is_transient_false(
        self, mock_anthropic_client, sample_indexes
    ):
        """ValueError (non-network) → is_transient=False."""
        mock_anthropic_client.create_message = AsyncMock(
            side_effect=ValueError("bad schema")
        )

        result = await run_lens(mock_anthropic_client, "prose", "scene text", sample_indexes)

        assert result.error is not None
        assert result.is_transient is False

    async def test_successful_call_has_no_error_and_not_transient(
        self, mock_anthropic_client, sample_indexes
    ):
        """Successful LLM call → error=None, is_transient=False."""
        mock_anthropic_client.create_message = AsyncMock(
            return_value=LLMResponse(text="some output")
        )

        result = await run_lens(mock_anthropic_client, "prose", "scene text", sample_indexes)

        assert result.error is None
        assert result.is_transient is False


# ---------------------------------------------------------------------------
# Task 9: run_analysis early-exit on all-lens failure
# ---------------------------------------------------------------------------

_ALL_LENS_NAMES = [
    "prose", "structure", "logic", "clarity", "continuity", "dialogue", "horizon"
]


def _make_all_transient_results() -> list[LensResult]:
    return [
        LensResult(name, [], "", error="timeout", is_transient=True)
        for name in _ALL_LENS_NAMES
    ]


def _make_all_non_transient_results() -> list[LensResult]:
    return [
        LensResult(name, [], "", error="schema error", is_transient=False)
        for name in _ALL_LENS_NAMES
    ]


def _make_partial_failure_results() -> list[LensResult]:
    """3/7 lenses fail (non-transient), 4 succeed."""
    results = []
    for i, name in enumerate(_ALL_LENS_NAMES):
        if i < 3:
            results.append(LensResult(name, [], "", error="fail", is_transient=False))
        else:
            results.append(LensResult(name, [], "some output"))
    return results


class TestRunAnalysisEarlyExit:
    """Tests for run_analysis early-exit via AllLensesFailedError."""

    async def test_all_transient_failures_raise_all_lenses_failed_transient(
        self, mock_anthropic_client, sample_indexes
    ):
        """All 7 lenses fail transiently → AllLensesFailedError(is_transient=True),
        coordinator never called."""
        transient_results = _make_all_transient_results()

        with patch(
            "orchestrator.runtime.api.run_lens",
            new_callable=AsyncMock,
        ) as mock_run_lens, patch(
            "orchestrator.runtime.api.run_coordinator_chunked",
            new_callable=AsyncMock,
        ) as mock_coord:
            mock_run_lens.side_effect = transient_results

            with pytest.raises(AllLensesFailedError) as exc_info:
                await run_analysis(mock_anthropic_client, "scene text", sample_indexes)

        assert exc_info.value.is_transient is True
        mock_coord.assert_not_called()

    async def test_all_non_transient_failures_raise_all_lenses_failed_not_transient(
        self, mock_anthropic_client, sample_indexes
    ):
        """All 7 lenses fail non-transiently → AllLensesFailedError(is_transient=False)."""
        non_transient_results = _make_all_non_transient_results()

        with patch(
            "orchestrator.runtime.api.run_lens",
            new_callable=AsyncMock,
        ) as mock_run_lens, patch(
            "orchestrator.runtime.api.run_coordinator_chunked",
            new_callable=AsyncMock,
        ) as mock_coord:
            mock_run_lens.side_effect = non_transient_results

            with pytest.raises(AllLensesFailedError) as exc_info:
                await run_analysis(mock_anthropic_client, "scene text", sample_indexes)

        assert exc_info.value.is_transient is False
        mock_coord.assert_not_called()

    async def test_partial_failures_call_coordinator(
        self, mock_anthropic_client, sample_indexes
    ):
        """3/7 lenses fail → coordinator is called with partial results (existing behavior)."""
        partial_results = _make_partial_failure_results()
        coordinator_output = {
            "findings": [],
            "glossary_issues": [],
            "conflicts": [],
            "ambiguities": [],
            "summary": {
                "prose": {"critical": 0, "major": 0, "minor": 0},
                "structure": {"critical": 0, "major": 0, "minor": 0},
                "coherence": {"critical": 0, "major": 0, "minor": 0},
            },
        }

        with patch(
            "orchestrator.runtime.api.run_lens",
            new_callable=AsyncMock,
        ) as mock_run_lens, patch(
            "orchestrator.runtime.api.run_coordinator_chunked",
            new_callable=AsyncMock,
        ) as mock_coord:
            mock_run_lens.side_effect = partial_results
            mock_coord.return_value = coordinator_output

            # Must NOT raise AllLensesFailedError
            result = await run_analysis(mock_anthropic_client, "scene text", sample_indexes)

        assert "findings" in result
        mock_coord.assert_called_once()
