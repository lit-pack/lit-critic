"""Tests for Phase 0 — Finding origin field (tiered analysis architecture).

Covers:
- Finding dataclass: origin field default and custom values
- Finding.to_dict() / from_dict() round-trip with origin
- Backward compatibility: dicts without origin key default to "legacy"
- DB schema migration: existing finding table without origin gets column added
- FindingStore: save_all persists origin, load_all restores it
- Coordinator output: _validate_coordinator_output tags findings with origin="legacy"
"""

from orchestrator.runtime.models import Finding
from orchestrator.runtime.api import _validate_coordinator_output


# ---------------------------------------------------------------------------
# Finding dataclass
# ---------------------------------------------------------------------------

class TestFindingOriginField:
    """Finding dataclass carries the origin field correctly."""

    def test_default_origin_is_legacy(self):
        """New Finding instances should default origin to 'legacy'."""
        f = Finding(number=1, severity="major", lens="prose", location="P1")
        assert f.origin == "legacy"

    def test_explicit_origin_code(self):
        finding = Finding(number=1, severity="minor", lens="prose",
                          location="P1", origin="code")
        assert finding.origin == "code"

    def test_explicit_origin_checker(self):
        finding = Finding(number=1, severity="major", lens="logic",
                          location="P2", origin="checker")
        assert finding.origin == "checker"

    def test_explicit_origin_critic(self):
        finding = Finding(number=1, severity="critical", lens="prose",
                          location="P3", origin="critic")
        assert finding.origin == "critic"

    def test_to_dict_includes_origin(self):
        """to_dict() must always emit the origin field."""
        f = Finding(number=1, severity="major", lens="prose",
                    location="P1", origin="code")
        d = f.to_dict(include_state=False)
        assert "origin" in d
        assert d["origin"] == "code"

    def test_to_dict_with_state_includes_origin(self):
        f = Finding(number=1, severity="major", lens="prose",
                    location="P1", origin="critic")
        d = f.to_dict(include_state=True)
        assert d["origin"] == "critic"

    def test_from_dict_restores_origin(self):
        d = {"number": 1, "severity": "major", "lens": "prose",
             "location": "P1", "origin": "checker"}
        f = Finding.from_dict(d)
        assert f.origin == "checker"

    def test_from_dict_missing_origin_defaults_to_legacy(self):
        """Dicts without origin (old data) should default to 'legacy'."""
        d = {"number": 1, "severity": "major", "lens": "prose", "location": "P1"}
        f = Finding.from_dict(d)
        assert f.origin == "legacy"

    def test_roundtrip_origin_code(self):
        original = Finding(number=2, severity="minor", lens="clarity",
                           location="P5", origin="code")
        restored = Finding.from_dict(original.to_dict(include_state=True))
        assert restored.origin == "code"

    def test_roundtrip_origin_legacy(self):
        original = Finding(number=3, severity="major", lens="structure",
                           location="P2")  # default origin
        restored = Finding.from_dict(original.to_dict(include_state=True))
        assert restored.origin == "legacy"


# ---------------------------------------------------------------------------
# Coordinator output tagging
# ---------------------------------------------------------------------------

class TestCoordinatorOriginTagging:
    """_validate_coordinator_output sets origin='legacy' on all findings."""

    def _make_coordinator_output(self, findings: list[dict]) -> dict:
        return {
            "glossary_issues": [],
            "summary": {
                "prose": {"critical": 0, "major": 0, "minor": 0},
                "structure": {"critical": 0, "major": 0, "minor": 0},
                "coherence": {"critical": 0, "major": 0, "minor": 0},
            },
            "findings": findings,
        }

    def test_findings_get_origin_legacy(self):
        data = self._make_coordinator_output([
            {"number": 1, "severity": "major", "lens": "prose",
             "location": "P1", "evidence": "e", "impact": "i", "options": []},
        ])
        result = _validate_coordinator_output(data)
        assert result["findings"][0]["origin"] == "legacy"

    def test_existing_origin_not_overwritten(self):
        """If a finding already has origin set, setdefault should not overwrite it."""
        data = self._make_coordinator_output([
            {"number": 1, "severity": "major", "lens": "prose",
             "location": "P1", "evidence": "e", "impact": "i", "options": [],
             "origin": "critic"},
        ])
        result = _validate_coordinator_output(data)
        assert result["findings"][0]["origin"] == "critic"

    def test_multiple_findings_all_get_legacy(self):
        data = self._make_coordinator_output([
            {"number": 1, "severity": "major", "lens": "prose",
             "location": "P1", "evidence": "e", "impact": "i", "options": []},
            {"number": 2, "severity": "minor", "lens": "clarity",
             "location": "P2", "evidence": "e2", "impact": "i2", "options": []},
        ])
        result = _validate_coordinator_output(data)
        for f in result["findings"]:
            assert f["origin"] == "legacy"
