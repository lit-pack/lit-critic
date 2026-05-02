"""Tests for ``orchestrator.runtime.models`` module."""

import pytest
from orchestrator.runtime.models import Finding, LearningData, LensResult, SessionState


class TestLearningData:
    """Tests for LearningData dataclass."""
    
    def test_default_values(self):
        """LearningData should have sensible defaults."""
        learning = LearningData()
        
        assert learning.project_name == "Unknown"
        assert learning.review_count == 0
        assert learning.preferences == []
        assert learning.blind_spots == []
        assert learning.resolutions == []
        assert learning.ambiguity_intentional == []
        assert learning.ambiguity_accidental == []
        assert learning.session_rejections == []
        assert learning.session_acceptances == []
        assert learning.session_ambiguity_answers == []
    
    def test_custom_values(self):
        """LearningData should accept custom values."""
        learning = LearningData(
            project_name="My Novel",
            review_count=5,
        )
        
        assert learning.project_name == "My Novel"
        assert learning.review_count == 5
    
    def test_lists_are_mutable(self):
        """Each instance should have its own mutable lists."""
        learning1 = LearningData()
        learning2 = LearningData()
        
        learning1.preferences.append({"test": "value"})
        
        assert len(learning1.preferences) == 1
        assert len(learning2.preferences) == 0


class TestFinding:
    """Tests for Finding dataclass."""
    
    def test_default_status(self):
        """Finding should default to 'pending' status."""
        finding = Finding(
            number=1,
            severity="major",
            lens="prose",
            location="test",
            evidence="test",
            impact="test",
            options=["option1"],
        )

        assert finding.status == "pending"
    
    def test_to_dict_without_state(self, sample_finding):
        """to_dict without state should not include status fields."""
        result = sample_finding.to_dict(include_state=False)
        
        assert "number" in result
        assert "severity" in result
        assert "lens" in result
        assert "location" in result
        assert "evidence" in result
        assert "impact" in result
        assert "options" in result
        assert "flagged_by" in result
        assert "ambiguity_type" in result
        assert "status" not in result
        assert "author_response" not in result
    
    def test_to_dict_with_state(self, sample_finding):
        """to_dict with state should include status and discussion_turns fields."""
        sample_finding.status = "accepted"

        result = sample_finding.to_dict(include_state=True)

        assert result["status"] == "accepted"
        assert "discussion_turns" in result
    
    def test_from_dict(self, sample_finding_dict):
        """from_dict should correctly create a Finding."""
        finding = Finding.from_dict(sample_finding_dict)
        
        assert finding.number == sample_finding_dict["number"]
        assert finding.severity == sample_finding_dict["severity"]
        assert finding.lens == sample_finding_dict["lens"]
        assert finding.location == sample_finding_dict["location"]
        assert finding.evidence == sample_finding_dict["evidence"]
        assert finding.impact == sample_finding_dict["impact"]
        assert finding.options == sample_finding_dict["options"]
        assert finding.flagged_by == sample_finding_dict["flagged_by"]
        assert finding.ambiguity_type == sample_finding_dict["ambiguity_type"]
    
    def test_from_dict_with_state(self, sample_finding_dict):
        """from_dict should restore status if present."""
        sample_finding_dict["status"] = "rejected"

        finding = Finding.from_dict(sample_finding_dict)

        assert finding.status == "rejected"
    
    def test_from_dict_with_defaults(self):
        """from_dict should use defaults for missing fields."""
        minimal_dict = {"number": 1}
        finding = Finding.from_dict(minimal_dict)
        
        assert finding.number == 1
        assert finding.severity == "minor"
        assert finding.lens == "unknown"
        assert finding.location == ""
        assert finding.options == []
        assert finding.flagged_by == []
    
    def test_line_fields_default_none(self):
        """line_start and line_end should default to None."""
        finding = Finding(
            number=1, severity="major", lens="prose",
            location="test",
        )
        assert finding.line_start is None
        assert finding.line_end is None
        assert finding.stale is False

    def test_line_fields_in_to_dict(self):
        """to_dict should include line_start, line_end, and stale."""
        finding = Finding(
            number=1, severity="major", lens="prose",
            location="test", line_start=5, line_end=10,
        )
        result = finding.to_dict(include_state=False)
        assert result["line_start"] == 5
        assert result["line_end"] == 10
        assert result["scene_path"] is None
        assert result["stale"] is False

    def test_scene_path_roundtrip(self):
        """to_dict/from_dict should preserve finding.scene_path."""
        original = Finding(
            number=1,
            severity="major",
            lens="prose",
            location="P1",
            scene_path="/book/ch01-scene02.md",
        )

        exported = original.to_dict(include_state=True)
        restored = Finding.from_dict(exported)

        assert restored.scene_path == "/book/ch01-scene02.md"

    def test_line_fields_from_dict(self):
        """from_dict should restore line_start, line_end, and stale."""
        data = {
            "number": 1, "severity": "major", "lens": "prose",
            "location": "P1", "line_start": 3, "line_end": 7, "stale": True,
        }
        finding = Finding.from_dict(data)
        assert finding.line_start == 3
        assert finding.line_end == 7
        assert finding.stale is True

    def test_from_dict_line_defaults(self):
        """from_dict should default line fields to None/False."""
        finding = Finding.from_dict({"number": 1})
        assert finding.line_start is None
        assert finding.line_end is None
        assert finding.stale is False

    def test_roundtrip(self, sample_finding_dict):
        """to_dict and from_dict should be inverse operations."""
        original = Finding.from_dict(sample_finding_dict)
        original.status = "accepted"

        exported = original.to_dict(include_state=True)
        restored = Finding.from_dict(exported)

        assert restored.number == original.number
        assert restored.severity == original.severity
        assert restored.lens == original.lens
        assert restored.location == original.location
        assert restored.status == original.status

    def test_roundtrip_with_line_numbers(self):
        """to_dict/from_dict should preserve line numbers and stale flag."""
        original = Finding(
            number=1, severity="major", lens="prose",
            location="P1", line_start=10, line_end=15,
        )
        original.stale = True

        exported = original.to_dict(include_state=True)
        restored = Finding.from_dict(exported)

        assert restored.line_start == 10
        assert restored.line_end == 15
        assert restored.stale is True


class TestLensResult:
    """Tests for LensResult dataclass."""
    
    def test_default_error(self):
        """LensResult should default to no error."""
        result = LensResult(
            lens_name="prose",
            findings=[],
            raw_output="[]"
        )
        
        assert result.error is None
    
    def test_with_error(self):
        """LensResult should store error message."""
        result = LensResult(
            lens_name="prose",
            findings=[],
            raw_output="",
            error="API timeout"
        )
        
        assert result.error == "API timeout"


class TestSessionState:
    """Tests for SessionState dataclass."""
    
    def test_default_collections(self, mock_anthropic_client, temp_project_dir, sample_indexes):
        """SessionState should initialize with empty collections."""
        state = SessionState(
            client=mock_anthropic_client,
            scene_content="Test scene",
            scene_path="/test/scene.md",
            project_path=temp_project_dir,
            indexes=sample_indexes,
        )
        
        assert state.findings == []
        assert state.glossary_issues == []
        assert state.scene_paths == []
        assert state.scene_line_map == []
        assert isinstance(state.learning, LearningData)
    
    def test_custom_learning(self, mock_anthropic_client, temp_project_dir, sample_indexes, sample_learning_data):
        """SessionState should accept custom learning data."""
        state = SessionState(
            client=mock_anthropic_client,
            scene_content="Test scene",
            scene_path="/test/scene.md",
            project_path=temp_project_dir,
            indexes=sample_indexes,
            learning=sample_learning_data,
        )
        
        assert state.learning.project_name == "Test Novel"
        assert state.learning.review_count == 3

    def test_scene_paths_and_line_map_custom_values(self, mock_anthropic_client, temp_project_dir, sample_indexes):
        """SessionState should accept precomputed multi-scene metadata."""
        state = SessionState(
            client=mock_anthropic_client,
            scene_content="combined",
            scene_path="/test/scene01.md",
            project_path=temp_project_dir,
            indexes=sample_indexes,
            scene_paths=["/test/scene01.md", "/test/scene02.md"],
            scene_line_map=[
                {"scene_path": "/test/scene01.md", "global_start": 2, "global_end": 10},
                {"scene_path": "/test/scene02.md", "global_start": 12, "global_end": 20},
            ],
        )

        assert state.scene_paths == ["/test/scene01.md", "/test/scene02.md"]
        assert len(state.scene_line_map) == 2
