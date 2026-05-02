"""
Tests for ``orchestrator.runtime.utils`` module.

Covers:
- number_lines: line number prepending
- compute_line_mapping: diff-based line mapping
- adjust_finding_lines: per-finding line adjustment
- apply_scene_change: batch adjustment of remaining findings
"""

import pytest
from orchestrator.runtime.utils import (
    concatenate_scenes,
    map_global_range_to_scene,
    remap_location_line_range,
    number_lines,
    compute_line_mapping,
    adjust_finding_lines,
    apply_scene_change,
)
from orchestrator.runtime.models import Finding


class TestNumberLines:
    """Tests for number_lines function."""

    def test_basic_numbering(self):
        """Lines should be numbered starting from 1."""
        text = "first\nsecond\nthird"
        result = number_lines(text)
        lines = result.split('\n')
        assert lines[0] == "L001: first"
        assert lines[1] == "L002: second"
        assert lines[2] == "L003: third"

    def test_single_line(self):
        """A single-line text should get L001 prefix."""
        result = number_lines("only line")
        assert result == "L001: only line"

    def test_empty_string(self):
        """An empty string should produce a single numbered empty line."""
        result = number_lines("")
        assert result == "L001: "

    def test_width_adapts_to_line_count(self):
        """Width should grow for texts with many lines."""
        lines = '\n'.join(f"line {i}" for i in range(1, 1001))
        result = number_lines(lines)
        first = result.split('\n')[0]
        # 1000 lines → 4-digit width
        assert first.startswith("L0001: ")
        last = result.split('\n')[-1]
        assert last.startswith("L1000: ")

    def test_preserves_empty_lines(self):
        """Empty lines in the source should be preserved."""
        text = "first\n\nthird"
        result = number_lines(text)
        lines = result.split('\n')
        assert lines[1] == "L002: "

    def test_preserves_indentation(self):
        """Leading whitespace in original lines should be preserved."""
        text = "no indent\n  two spaces\n    four spaces"
        result = number_lines(text)
        lines = result.split('\n')
        assert lines[1] == "L002:   two spaces"
        assert lines[2] == "L003:     four spaces"


class TestMultiSceneUtilities:
    """Tests for multi-scene concatenation + line mapping utilities."""

    def test_concatenate_scenes_builds_boundaries_and_map(self):
        text, line_map = concatenate_scenes([
            ("/book/01_scene.txt", "A1\nA2"),
            ("/book/02_scene.txt", "B1"),
        ])

        assert "===== SCENE BOUNDARY: 01_scene.txt =====" in text
        assert "===== SCENE BOUNDARY: 02_scene.txt =====" in text
        assert len(line_map) == 2
        assert line_map[0]["scene_path"] == "/book/01_scene.txt"
        assert line_map[0]["global_start"] == 2
        assert line_map[0]["global_end"] == 3
        assert line_map[1]["scene_path"] == "/book/02_scene.txt"

    def test_map_global_range_to_scene_returns_local_lines(self):
        _, line_map = concatenate_scenes([
            ("/book/01_scene.txt", "A1\nA2"),
            ("/book/02_scene.txt", "B1\nB2"),
        ])

        scene_path, local_start, local_end = map_global_range_to_scene(line_map, 6, 7)
        assert scene_path == "/book/02_scene.txt"
        assert local_start == 1
        assert local_end == 2

    def test_remap_location_line_range_updates_first_range(self):
        location = "L120-L124, starting 'She moved...'"
        remapped = remap_location_line_range(location, 12, 16)
        assert remapped == "L12-L16, starting 'She moved...'"

    def test_remap_location_line_range_updates_single_line(self):
        location = "L120, unclear beat"
        remapped = remap_location_line_range(location, 7, None)
        assert remapped == "L7, unclear beat"

    def test_remap_location_line_range_leaves_text_without_l_range(self):
        location = "Paragraph 3 near midpoint"
        remapped = remap_location_line_range(location, 7, 9)
        assert remapped == location

    def test_remap_location_line_range_requires_line_start(self):
        location = "L120-L124, starting 'She moved...'"
        remapped = remap_location_line_range(location, None, None)
        assert remapped == location


class TestComputeLineMapping:
    """Tests for compute_line_mapping function."""

    def test_identical_texts(self):
        """Identical texts should map every line to itself."""
        text = "a\nb\nc"
        result = compute_line_mapping(text, text)
        assert result["mapping"] == {1: 1, 2: 2, 3: 3}
        assert result["deleted"] == set()
        assert result["inserted"] == set()

    def test_line_deleted(self):
        """Deleting a line should mark it as deleted and shift subsequent lines."""
        old = "a\nb\nc"
        new = "a\nc"
        result = compute_line_mapping(old, new)
        assert 2 in result["deleted"]  # 'b' was deleted
        assert result["mapping"][1] == 1  # 'a' stays at 1
        assert result["mapping"][3] == 2  # 'c' moves from 3 to 2

    def test_line_inserted(self):
        """Inserting a line should mark it as inserted and shift subsequent lines."""
        old = "a\nc"
        new = "a\nb\nc"
        result = compute_line_mapping(old, new)
        assert 2 in result["inserted"]  # 'b' is new
        assert result["mapping"][1] == 1  # 'a' stays at 1
        assert result["mapping"][2] == 3  # 'c' moves from 2 to 3

    def test_line_replaced(self):
        """Replacing a line should mark old as deleted and new as inserted."""
        old = "a\nb\nc"
        new = "a\nB\nc"
        result = compute_line_mapping(old, new)
        assert 2 in result["deleted"]    # old 'b' deleted
        assert 2 in result["inserted"]   # new 'B' inserted
        assert result["mapping"][1] == 1
        assert result["mapping"][3] == 3

    def test_multiple_changes(self):
        """Multiple deletions and insertions should all be tracked."""
        old = "a\nb\nc\nd\ne"
        new = "a\nX\nc\nY\nZ\ne"
        result = compute_line_mapping(old, new)
        # 'b' replaced by 'X', 'd' replaced by 'Y'+'Z'
        assert 2 in result["deleted"]
        assert 4 in result["deleted"]
        assert result["mapping"][1] == 1  # 'a'
        assert result["mapping"][3] == 3  # 'c'
        assert result["mapping"][5] == 6  # 'e' shifted

    def test_empty_old_text(self):
        """Starting from empty: everything is inserted."""
        result = compute_line_mapping("", "a\nb")
        assert result["mapping"] == {}
        assert result["inserted"] == {1, 2}

    def test_empty_new_text(self):
        """Deleting everything: all lines deleted."""
        result = compute_line_mapping("a\nb", "")
        assert result["mapping"] == {}
        assert result["deleted"] == {1, 2}

    def test_prepend_lines(self):
        """Prepending lines should shift all existing lines."""
        old = "a\nb"
        new = "x\ny\na\nb"
        result = compute_line_mapping(old, new)
        assert result["mapping"][1] == 3  # 'a' moved from 1 to 3
        assert result["mapping"][2] == 4  # 'b' moved from 2 to 4
        assert 1 in result["inserted"]
        assert 2 in result["inserted"]


class TestAdjustFindingLines:
    """Tests for adjust_finding_lines function."""

    def _make_finding(self, line_start=None, line_end=None):
        return Finding(
            number=1, severity="major", lens="prose",
            location="Test", line_start=line_start, line_end=line_end,
        )

    def test_no_lines_returns_no_lines(self):
        """Finding without line numbers returns 'no_lines'."""
        finding = self._make_finding()
        mapping = {"mapping": {}, "deleted": set(), "inserted": set()}
        result = adjust_finding_lines(finding, mapping)
        assert result == "no_lines"

    def test_adjusted_single_line(self):
        """Finding with a single line that maps should be adjusted."""
        finding = self._make_finding(line_start=3)
        mapping = {"mapping": {3: 5}, "deleted": set(), "inserted": set()}
        result = adjust_finding_lines(finding, mapping)
        assert result == "adjusted"
        assert finding.line_start == 5
        assert finding.line_end is None

    def test_adjusted_line_range(self):
        """Finding with a line range should have both endpoints adjusted."""
        finding = self._make_finding(line_start=2, line_end=4)
        mapping = {"mapping": {2: 3, 3: 4, 4: 5}, "deleted": set(), "inserted": set()}
        result = adjust_finding_lines(finding, mapping)
        assert result == "adjusted"
        assert finding.line_start == 3
        assert finding.line_end == 5

    def test_stale_when_deleted(self):
        """Finding overlapping a deleted line should be marked stale."""
        finding = self._make_finding(line_start=2, line_end=4)
        mapping = {"mapping": {2: 2, 4: 3}, "deleted": {3}, "inserted": set()}
        result = adjust_finding_lines(finding, mapping)
        assert result == "stale"
        assert finding.stale is True

    def test_stale_when_start_not_in_mapping(self):
        """Finding whose start line is not in mapping should be stale."""
        finding = self._make_finding(line_start=5)
        mapping = {"mapping": {1: 1, 2: 2}, "deleted": set(), "inserted": set()}
        result = adjust_finding_lines(finding, mapping)
        assert result == "stale"
        assert finding.stale is True

    def test_stale_when_any_line_in_deleted(self):
        """Even if start is fine, if any line in range is deleted → stale."""
        finding = self._make_finding(line_start=1, line_end=3)
        mapping = {"mapping": {1: 1, 3: 2}, "deleted": {2}, "inserted": set()}
        result = adjust_finding_lines(finding, mapping)
        assert result == "stale"

    def test_adjusted_preserves_none_line_end(self):
        """If line_end was None, it should stay None after adjustment."""
        finding = self._make_finding(line_start=2)
        mapping = {"mapping": {2: 10}, "deleted": set(), "inserted": set()}
        result = adjust_finding_lines(finding, mapping)
        assert result == "adjusted"
        assert finding.line_start == 10
        assert finding.line_end is None


class TestApplySceneChange:
    """Tests for apply_scene_change function."""

    def _make_findings(self, specs):
        """Create findings from a list of (line_start, line_end) tuples."""
        return [
            Finding(
                number=i + 1, severity="major", lens="prose",
                location=f"P{i+1}", line_start=ls, line_end=le,
            )
            for i, (ls, le) in enumerate(specs)
        ]

    def test_no_change(self):
        """Identical text should return all zeros."""
        text = "a\nb\nc"
        findings = self._make_findings([(1, 1), (2, 3)])
        result = apply_scene_change(findings, text, text)
        # All lines map to themselves → all adjusted (no shift needed, but 'adjusted' status)
        assert result["adjusted"] == 2
        assert result["stale"] == 0

    def test_shifted_lines(self):
        """Inserting a line at top shifts all findings."""
        old = "a\nb\nc"
        new = "x\na\nb\nc"
        findings = self._make_findings([(1, 1), (2, 3)])
        result = apply_scene_change(findings, old, new)
        assert result["adjusted"] == 2
        assert findings[0].line_start == 2  # 'a' shifted from 1 to 2
        assert findings[1].line_start == 3  # 'b' shifted from 2 to 3
        assert findings[1].line_end == 4    # 'c' shifted from 3 to 4

    def test_stale_findings(self):
        """Deleting lines in a finding's range should mark it stale."""
        old = "a\nb\nc\nd"
        new = "a\nd"  # deleted b and c
        findings = self._make_findings([(2, 3), (4, 4)])
        result = apply_scene_change(findings, old, new)
        assert result["stale"] == 1    # finding at lines 2-3
        assert result["adjusted"] == 1  # finding at line 4 → now line 2
        assert findings[0].stale is True
        assert findings[1].line_start == 2

    def test_start_index(self):
        """Only findings from start_index onward should be adjusted."""
        old = "a\nb\nc"
        new = "x\na\nb\nc"
        findings = self._make_findings([(1, 1), (2, 2), (3, 3)])
        result = apply_scene_change(findings, old, new, start_index=1)
        assert result["total"] == 2  # Only examined findings[1] and findings[2]
        # findings[0] should be untouched
        assert findings[0].line_start == 1
        # findings[1] and [2] should be shifted
        assert findings[1].line_start == 3
        assert findings[2].line_start == 4

    def test_no_lines_counted(self):
        """Findings without line numbers should be counted as no_lines."""
        old = "a\nb"
        new = "a\nx\nb"
        findings = self._make_findings([(1, 1), (None, None)])
        result = apply_scene_change(findings, old, new)
        assert result["no_lines"] == 1
        assert result["adjusted"] == 1

    def test_mixed_results(self):
        """Mix of adjusted, stale, and no_lines findings."""
        old = "a\nb\nc\nd"
        new = "a\nX\nc\ny\nd"  # replaced b with X, inserted y before d
        findings = [
            Finding(number=1, severity="major", lens="prose",
                    location="P1", line_start=1, line_end=1),  # 'a' → adjusted
            Finding(number=2, severity="major", lens="prose",
                    location="P2", line_start=2, line_end=2),  # 'b' → stale (replaced)
            Finding(number=3, severity="minor", lens="clarity",
                    location="P3"),                            # no lines
            Finding(number=4, severity="major", lens="prose",
                    location="P4", line_start=4, line_end=4),  # 'd' → adjusted (shifted)
        ]
        result = apply_scene_change(findings, old, new)
        assert result["adjusted"] == 2
        assert result["stale"] == 1
        assert result["no_lines"] == 1
        assert result["total"] == 4

    def test_empty_findings_list(self):
        """Empty findings list should return all zeros."""
        result = apply_scene_change([], "a", "b")
        assert result["total"] == 0
        assert result["adjusted"] == 0
        assert result["stale"] == 0
        assert result["no_lines"] == 0
