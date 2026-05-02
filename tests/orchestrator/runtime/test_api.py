"""
Tests for orchestrator.runtime.api module.

Updated to use the provider-agnostic LLMClient interface.
All client mocks now use create_message() and create_message_with_tool()
instead of the old Anthropic-specific messages.create().
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from orchestrator.runtime.api import (
    run_lens, run_coordinator, run_analysis,
    _extract_tool_use_input, _validate_coordinator_output,
)
from orchestrator.runtime.models import LensResult, CoordinatorError
from orchestrator.runtime.llm.base import LLMResponse, LLMToolResponse


class TestRunLens:
    """Tests for run_lens function."""

    async def test_returns_lens_result(self, mock_anthropic_client, sample_indexes):
        """run_lens should return a LensResult."""
        mock_anthropic_client.create_message = AsyncMock(
            return_value=LLMResponse(text='[]')
        )

        result = await run_lens(mock_anthropic_client, "prose", "Test scene", sample_indexes)

        assert isinstance(result, LensResult)
        assert result.lens_name == "prose"

    async def test_stores_raw_output(self, mock_anthropic_client, sample_indexes):
        """run_lens should store raw API output."""
        expected_output = '[{"severity": "major", "location": "test"}]'
        mock_anthropic_client.create_message = AsyncMock(
            return_value=LLMResponse(text=expected_output)
        )

        result = await run_lens(mock_anthropic_client, "prose", "Test scene", sample_indexes)

        assert result.raw_output == expected_output

    async def test_handles_api_error(self, mock_anthropic_client, sample_indexes):
        """run_lens should capture errors gracefully."""
        mock_anthropic_client.create_message = AsyncMock(
            side_effect=Exception("API Error")
        )

        result = await run_lens(mock_anthropic_client, "prose", "Test scene", sample_indexes)

        assert result.error == "API Error"
        assert result.raw_output == ""

    async def test_calls_api_with_correct_params(self, mock_anthropic_client, sample_indexes):
        """run_lens should pass model and max_tokens to create_message."""
        mock_anthropic_client.create_message = AsyncMock(
            return_value=LLMResponse(text='[]')
        )

        await run_lens(mock_anthropic_client, "prose", "Test scene", sample_indexes)

        call_kwargs = mock_anthropic_client.create_message.call_args.kwargs
        assert "model" in call_kwargs
        assert "max_tokens" in call_kwargs
        assert "messages" in call_kwargs

    async def test_all_lenses_work(self, mock_anthropic_client, sample_indexes):
        """All lens types should be callable."""
        mock_anthropic_client.create_message = AsyncMock(
            return_value=LLMResponse(text='[]')
        )

        lens_names = ["prose", "structure", "logic", "clarity", "continuity", "dialogue", "horizon"]

        for lens_name in lens_names:
            result = await run_lens(mock_anthropic_client, lens_name, "Test scene", sample_indexes)
            assert result.lens_name == lens_name
            assert result.error is None


class TestExtractToolUseInput:
    """Tests for _extract_tool_use_input helper."""

    def test_extracts_tool_input(self):
        """Should extract tool_input from an LLMToolResponse."""
        data = {"findings": [], "glossary_issues": []}
        response = LLMToolResponse(tool_input=data)
        assert _extract_tool_use_input(response) == data

    def test_raises_on_empty_tool_input(self):
        """Should raise CoordinatorError when tool_input is empty."""
        response = LLMToolResponse(tool_input={}, raw_text="Here is the JSON: {}")
        with pytest.raises(CoordinatorError, match="no report_findings tool call"):
            _extract_tool_use_input(response)

    def test_raises_on_unexpected_response_type(self):
        """Should raise CoordinatorError for non-LLMToolResponse objects."""
        response = {"not": "an LLMToolResponse"}
        with pytest.raises(CoordinatorError, match="Unexpected response type"):
            _extract_tool_use_input(response)


class TestValidateCoordinatorOutput:
    """Tests for _validate_coordinator_output helper."""

    def test_valid_output_passes(self, sample_coordinator_output):
        """A well-formed output should pass validation unchanged."""
        result = _validate_coordinator_output(sample_coordinator_output)
        assert result["findings"][0]["severity"] == "major"
        assert len(result["findings"]) == 2

    def test_missing_required_top_key_raises(self):
        """Missing top-level key should raise CoordinatorError."""
        data = {"glossary_issues": [], "summary": {}}  # missing 'findings'
        with pytest.raises(CoordinatorError, match="missing required key 'findings'"):
            _validate_coordinator_output(data)

    def test_findings_not_a_list_raises(self):
        """Non-list findings should raise CoordinatorError."""
        data = {"glossary_issues": [], "summary": {}, "findings": "not a list"}
        with pytest.raises(CoordinatorError, match="not a list"):
            _validate_coordinator_output(data)

    def test_finding_missing_required_field_raises(self):
        """A finding missing a required field should raise CoordinatorError."""
        data = {
            "glossary_issues": [],
            "summary": {"prose": {"critical": 0, "major": 0, "minor": 0},
                        "structure": {"critical": 0, "major": 0, "minor": 0},
                        "coherence": {"critical": 0, "major": 0, "minor": 0}},
            "findings": [{"number": 1, "severity": "major"}]  # missing lens, location, etc.
        }
        with pytest.raises(CoordinatorError, match="missing required field"):
            _validate_coordinator_output(data)

    def test_defaults_for_optional_fields(self):
        """Optional finding fields should get defaults."""
        data = {
            "glossary_issues": [],
            "summary": {"prose": {"critical": 0, "major": 1, "minor": 0},
                        "structure": {"critical": 0, "major": 0, "minor": 0},
                        "coherence": {"critical": 0, "major": 0, "minor": 0}},
            "findings": [{
                "number": 1,
                "severity": "major",
                "lens": "prose",
                "location": "Paragraph 1",
                "evidence": "Test evidence",
                "impact": "Test impact",
                "options": ["Fix it"],
                # flagged_by and ambiguity_type omitted
            }],
        }
        result = _validate_coordinator_output(data)
        finding = result["findings"][0]
        assert finding["flagged_by"] == ["prose"]
        assert finding["ambiguity_type"] is None

    def test_defaults_for_optional_top_level_keys(self):
        """Optional top-level keys (conflicts, ambiguities) should get defaults."""
        data = {
            "glossary_issues": [],
            "summary": {"prose": {"critical": 0, "major": 0, "minor": 0},
                        "structure": {"critical": 0, "major": 0, "minor": 0},
                        "coherence": {"critical": 0, "major": 0, "minor": 0}},
            "findings": [],
            # conflicts and ambiguities omitted
        }
        result = _validate_coordinator_output(data)
        assert result["conflicts"] == []
        assert result["ambiguities"] == []

    def test_normalises_severity(self):
        """Severity should be lowercased and stripped."""
        data = {
            "glossary_issues": [],
            "summary": {"prose": {"critical": 0, "major": 1, "minor": 0},
                        "structure": {"critical": 0, "major": 0, "minor": 0},
                        "coherence": {"critical": 0, "major": 0, "minor": 0}},
            "findings": [{
                "number": 1,
                "severity": "  Major ",
                "lens": "prose",
                "location": "Paragraph 1",
                "evidence": "Test",
                "impact": "Test",
                "options": ["Fix"],
            }],
        }
        result = _validate_coordinator_output(data)
        assert result["findings"][0]["severity"] == "major"

    def test_unrecognised_severity_defaults_to_major(self):
        """Unrecognised severity should default to 'major' with a warning."""
        data = {
            "glossary_issues": [],
            "summary": {"prose": {"critical": 0, "major": 1, "minor": 0},
                        "structure": {"critical": 0, "major": 0, "minor": 0},
                        "coherence": {"critical": 0, "major": 0, "minor": 0}},
            "findings": [{
                "number": 1,
                "severity": "high",
                "lens": "prose",
                "location": "Paragraph 1",
                "evidence": "Test",
                "impact": "Test",
                "options": ["Fix"],
            }],
        }
        result = _validate_coordinator_output(data)
        assert result["findings"][0]["severity"] == "major"

    def test_line_start_line_end_defaults(self):
        """line_start and line_end should default to None when absent."""
        data = {
            "glossary_issues": [],
            "summary": {"prose": {"critical": 0, "major": 1, "minor": 0},
                        "structure": {"critical": 0, "major": 0, "minor": 0},
                        "coherence": {"critical": 0, "major": 0, "minor": 0}},
            "findings": [{
                "number": 1, "severity": "major", "lens": "prose",
                "location": "P1", "evidence": "Test", "impact": "Test",
                "options": ["Fix"],
            }],
        }
        result = _validate_coordinator_output(data)
        assert result["findings"][0]["line_start"] is None
        assert result["findings"][0]["line_end"] is None

    def test_line_start_line_end_preserved(self):
        """Valid integer line_start/line_end should be preserved."""
        data = {
            "glossary_issues": [],
            "summary": {"prose": {"critical": 0, "major": 1, "minor": 0},
                        "structure": {"critical": 0, "major": 0, "minor": 0},
                        "coherence": {"critical": 0, "major": 0, "minor": 0}},
            "findings": [{
                "number": 1, "severity": "major", "lens": "prose",
                "location": "P1", "evidence": "Test", "impact": "Test",
                "options": ["Fix"], "line_start": 5, "line_end": 10,
            }],
        }
        result = _validate_coordinator_output(data)
        assert result["findings"][0]["line_start"] == 5
        assert result["findings"][0]["line_end"] == 10

    def test_non_integer_line_start_cleared(self):
        """Non-integer line_start should be cleared to None."""
        data = {
            "glossary_issues": [],
            "summary": {"prose": {"critical": 0, "major": 1, "minor": 0},
                        "structure": {"critical": 0, "major": 0, "minor": 0},
                        "coherence": {"critical": 0, "major": 0, "minor": 0}},
            "findings": [{
                "number": 1, "severity": "major", "lens": "prose",
                "location": "P1", "evidence": "Test", "impact": "Test",
                "options": ["Fix"], "line_start": "five", "line_end": 10,
            }],
        }
        result = _validate_coordinator_output(data)
        assert result["findings"][0]["line_start"] is None
        assert result["findings"][0]["line_end"] == 10

    def test_line_start_greater_than_line_end_swapped(self):
        """line_start > line_end should be swapped."""
        data = {
            "glossary_issues": [],
            "summary": {"prose": {"critical": 0, "major": 1, "minor": 0},
                        "structure": {"critical": 0, "major": 0, "minor": 0},
                        "coherence": {"critical": 0, "major": 0, "minor": 0}},
            "findings": [{
                "number": 1, "severity": "major", "lens": "prose",
                "location": "P1", "evidence": "Test", "impact": "Test",
                "options": ["Fix"], "line_start": 10, "line_end": 5,
            }],
        }
        result = _validate_coordinator_output(data)
        assert result["findings"][0]["line_start"] == 5
        assert result["findings"][0]["line_end"] == 10


class TestRunCoordinator:
    """Tests for run_coordinator function."""

    async def test_returns_dict_via_tool_use(
        self, mock_anthropic_client, sample_lens_results, sample_scene,
        sample_coordinator_output
    ):
        """run_coordinator should return a validated dict from tool_use response."""
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input=sample_coordinator_output)
        )

        result = await run_coordinator(
            mock_anthropic_client, sample_lens_results, sample_scene
        )

        assert isinstance(result, dict)
        assert "findings" in result
        assert len(result["findings"]) == 2

    async def test_passes_tool_definition(
        self, mock_anthropic_client, sample_lens_results, sample_scene,
        sample_coordinator_output
    ):
        """run_coordinator should pass tool_schema and tool_name in the API call."""
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input=sample_coordinator_output)
        )

        await run_coordinator(
            mock_anthropic_client, sample_lens_results, sample_scene
        )

        call_kwargs = mock_anthropic_client.create_message_with_tool.call_args.kwargs
        assert "tool_schema" in call_kwargs
        assert call_kwargs["tool_schema"]["name"] == "report_findings"
        assert call_kwargs["tool_name"] == "report_findings"

    async def test_raises_coordinator_error_on_no_tool_use(
        self, mock_anthropic_client, sample_lens_results, sample_scene
    ):
        """Should raise CoordinatorError when response has no tool input."""
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input={}, raw_text="Here is the output...")
        )

        with pytest.raises(CoordinatorError, match="no report_findings tool call"):
            await run_coordinator(
                mock_anthropic_client, sample_lens_results, sample_scene
            )

    async def test_raises_coordinator_error_on_invalid_output(
        self, mock_anthropic_client, sample_lens_results, sample_scene
    ):
        """Should raise CoordinatorError when tool output fails validation."""
        bad_output = {"glossary_issues": [], "summary": {}}  # missing 'findings'
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input=bad_output)
        )

        with pytest.raises(CoordinatorError, match="missing required key"):
            await run_coordinator(
                mock_anthropic_client, sample_lens_results, sample_scene
            )

    async def test_retries_on_transient_api_error(
        self, mock_anthropic_client, sample_lens_results, sample_scene,
        sample_coordinator_output
    ):
        """Should retry on transient API errors and succeed on later attempt."""
        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("Network blip")
            return LLMToolResponse(tool_input=sample_coordinator_output)

        mock_anthropic_client.create_message_with_tool = mock_create

        # Use max_retries=2 and patch sleep to avoid real delays
        with patch("orchestrator.runtime.api.asyncio.sleep", new_callable=AsyncMock):
            result = await run_coordinator(
                mock_anthropic_client, sample_lens_results, sample_scene,
                max_retries=2
            )

        assert call_count[0] == 2
        assert "findings" in result

    async def test_raises_after_all_retries_exhausted(
        self, mock_anthropic_client, sample_lens_results, sample_scene
    ):
        """Should raise CoordinatorError after exhausting all retries."""
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            side_effect=ConnectionError("Persistent failure")
        )

        with patch("orchestrator.runtime.api.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(CoordinatorError, match="failed after 2 attempts"):
                await run_coordinator(
                    mock_anthropic_client, sample_lens_results, sample_scene,
                    max_retries=2
                )

    async def test_no_retry_on_coordinator_error(
        self, mock_anthropic_client, sample_lens_results, sample_scene
    ):
        """CoordinatorError (structural) should NOT be retried — it raises immediately."""
        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            return LLMToolResponse(tool_input={}, raw_text="No tool use here")

        mock_anthropic_client.create_message_with_tool = mock_create

        with pytest.raises(CoordinatorError):
            await run_coordinator(
                mock_anthropic_client, sample_lens_results, sample_scene,
                max_retries=3
            )

        # Should have been called exactly once — no retry for structural errors
        assert call_count[0] == 1

    async def test_empty_findings_is_valid(
        self, mock_anthropic_client, sample_lens_results, sample_scene
    ):
        """An empty findings list is valid (scene has no issues)."""
        output = {
            "glossary_issues": [],
            "summary": {
                "prose": {"critical": 0, "major": 0, "minor": 0},
                "structure": {"critical": 0, "major": 0, "minor": 0},
                "coherence": {"critical": 0, "major": 0, "minor": 0},
            },
            "conflicts": [],
            "ambiguities": [],
            "findings": [],
        }
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input=output)
        )

        result = await run_coordinator(
            mock_anthropic_client, sample_lens_results, sample_scene
        )

        assert result["findings"] == []


class TestRunAnalysis:
    """Tests for run_analysis function."""

    async def test_runs_all_lenses_and_coordinator(
        self, mock_anthropic_client, sample_indexes, sample_scene,
        sample_coordinator_output
    ):
        """run_analysis should run 7 lenses (including horizon) then 3 chunked coordinator calls."""
        mock_anthropic_client.create_message = AsyncMock(
            side_effect=[
                LLMResponse(text='[]'),  # prose
                LLMResponse(text='[]'),  # structure
                LLMResponse(text='[]'),  # logic
                LLMResponse(text='[]'),  # clarity
                LLMResponse(text='[]'),  # continuity
                LLMResponse(text='[]'),  # dialogue
                LLMResponse(text='[{"category":"opportunity"}]'),  # horizon
            ]
        )
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input=sample_coordinator_output)
        )

        with patch('orchestrator.runtime.api.print'):
            result = await run_analysis(mock_anthropic_client, sample_scene, sample_indexes)

        assert mock_anthropic_client.create_message.call_count == 7  # 7 lenses incl. horizon
        assert mock_anthropic_client.create_message_with_tool.call_count == 3  # 3 coordinator chunks
        assert "findings" in result
        assert "horizon_observations" in result
        assert result["horizon_observations"] == '[{"category":"opportunity"}]'
        assert len(result["findings"]) >= 1  # dedup may reduce count

    async def test_run_analysis_always_runs_horizon_lens(
        self, mock_anthropic_client, sample_indexes, sample_scene,
        sample_coordinator_output
    ):
        """run_analysis should always execute all 7 lenses, including horizon."""
        mock_anthropic_client.create_message = AsyncMock(
            side_effect=[
                LLMResponse(text='[]'),  # prose
                LLMResponse(text='[]'),  # structure
                LLMResponse(text='[]'),  # logic
                LLMResponse(text='[]'),  # clarity
                LLMResponse(text='[]'),  # continuity
                LLMResponse(text='[]'),  # dialogue
                LLMResponse(text='[{"category":"opportunity"}]'),  # horizon
            ]
        )
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input=sample_coordinator_output)
        )

        with patch('orchestrator.runtime.api.print'):
            result = await run_analysis(mock_anthropic_client, sample_scene, sample_indexes)

        assert mock_anthropic_client.create_message.call_count == 7
        assert "horizon_observations" in result
        assert result["horizon_observations"] == '[{"category":"opportunity"}]'

    async def test_returns_coordinated_results(
        self, mock_anthropic_client, sample_indexes, sample_scene,
        sample_coordinator_output
    ):
        """run_analysis should return coordinator's validated output."""
        mock_anthropic_client.create_message = AsyncMock(
            return_value=LLMResponse(text='[]')
        )
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input=sample_coordinator_output)
        )

        with patch('orchestrator.runtime.api.print'):
            result = await run_analysis(mock_anthropic_client, sample_scene, sample_indexes)

        assert result["glossary_issues"] == []
        assert result["findings"][0]["severity"] == "major"

    async def test_handles_lens_failure(
        self, mock_anthropic_client, sample_indexes, sample_scene,
        sample_coordinator_output
    ):
        """run_analysis should handle individual lens failures gracefully."""
        call_count = [0]

        async def mock_create_message(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Lens failure")
            return LLMResponse(text='[]')

        mock_anthropic_client.create_message = mock_create_message
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input=sample_coordinator_output)
        )

        with patch('orchestrator.runtime.api.print'):
            result = await run_analysis(mock_anthropic_client, sample_scene, sample_indexes)

        assert "findings" in result

    async def test_raises_coordinator_error(
        self, mock_anthropic_client, sample_indexes, sample_scene
    ):
        """run_analysis should propagate CoordinatorError from coordinator."""
        mock_anthropic_client.create_message = AsyncMock(
            return_value=LLMResponse(text='[]')
        )
        # All coordinator calls return empty tool_input → CoordinatorError
        mock_anthropic_client.create_message_with_tool = AsyncMock(
            return_value=LLMToolResponse(tool_input={}, raw_text="Oops, no tool use")
        )

        with patch('orchestrator.runtime.api.print'):
            with pytest.raises(CoordinatorError):
                await run_analysis(mock_anthropic_client, sample_scene, sample_indexes)
