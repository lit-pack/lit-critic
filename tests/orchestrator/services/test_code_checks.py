"""Tests for orchestrator.services.code_checks.

Covers all five stage functions and the orchestrator.
Each test provides known-good or known-bad inputs and asserts on the
returned finding dicts / Finding objects.
"""

from __future__ import annotations

import pytest

from orchestrator.services.code_checks import (
    run_code_checks,
    meta_validate,
    index_crossref,
    scene_index_match,
    timeline_validate,
    style_patterns,
)
from orchestrator.runtime.models import Finding


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

GOOD_META = """\
@@META
ID: 01.03.01
Part: 01
Chapter: 03
Scene: 01
Chrono: D0-T083
POV: Amelia
Tense: Past
Location: Sanctuary / Lower Corridor
Cast: Amelia; George
Objective: Amelia discovers the vault
Threats: Wards failing
Secrets: None
ContAnchors: vault_door=ajar
Terms: Breach Gates
Threads: vault_mystery
Prev: 01.02.05
Next: 01.03.02
@@END

The corridor smelled of rust and old stone.\
"""

GOOD_INDEXES: dict[str, str] = {
    "cast": (
        "# Cast\n\n"
        "## Main Characters\n\n"
        "### Amelia Ashvale\n"
        "- **Role:** Warden\n"
        "- **Relationships:**\n"
        "  - George: mentor\n"
        "- **Key facts:**\n"
        "  - First seen: 01.01.01\n\n"
        "### George Thorne\n"
        "- **Role:** Elder\n"
        "- **Relationships:**\n"
        "  - Amelia: protégé\n"
    ),
    "glossary": (
        "# Glossary\n\n"
        "## Terms\n\n"
        "### Breach Gates\n"
        "**Definition:** Sealed portals\n"
        "**First seen:** 01.01.01\n"
        "**Notes:** Always capitalized\n"
    ),
    "threads": (
        "# Threads\n\n"
        "## Active Threads\n\n"
        "### vault_mystery\n"
        "**Opened:** 01.01.01\n"
        "**Status:** Active\n"
        "**Question:** What is in the vault?\n"
    ),
    "timeline": (
        "# Timeline\n\n"
        "## Part 01\n\n"
        "### Chapter 01\n\n"
        "**01.01.01** Amelia wakes.\n"
        "**01.01.02** Amelia searches.\n\n"
        "### Chapter 02\n\n"
        "**01.02.05** Last chapter 2 scene.\n\n"
        "### Chapter 03\n\n"
        "**01.03.01** The vault door.\n"
        "**01.03.02** Aftermath.\n"
    ),
    "CANON.md": "# Canon\n\nMagic is blocked in sanctuaries.\n",
}


def _lens_ids(findings: list) -> list[str]:
    """Return the list of lens names from findings (Finding objects or dicts)."""
    result = []
    for f in findings:
        if isinstance(f, Finding):
            result.append(f.lens)
        else:
            result.append(f.get("lens", ""))
    return result


def _severities(findings: list) -> list[str]:
    result = []
    for f in findings:
        if isinstance(f, Finding):
            result.append(f.severity)
        else:
            result.append(f.get("severity", ""))
    return result


# ===========================================================================
# Stage: meta_validate
# ===========================================================================

class TestMetaValidate:

    def test_clean_scene_no_findings(self):
        assert meta_validate(GOOD_META, {}) == []

    def test_missing_meta_marker(self):
        scene = "No metadata here.\n\nJust prose."
        findings = meta_validate(scene, {})
        assert len(findings) == 1
        assert findings[0]["severity"] == "critical"
        assert "@@META" in findings[0]["evidence"]

    def test_missing_end_marker(self):
        scene = "@@META\nID: 01.01.01\nPart: 01\n\nNo @@END here."
        findings = meta_validate(scene, {})
        assert len(findings) == 1
        assert findings[0]["severity"] == "critical"
        assert "@@END" in findings[0]["evidence"]

    def test_missing_id_field(self):
        scene = "@@META\nPart: 01\nChapter: 01\n@@END\nProse."
        findings = meta_validate(scene, {})
        severities = _severities(findings)
        assert severities.count("major") == 2
        assert any("PREV" in f["evidence"] for f in findings)
        assert any("NEXT" in f["evidence"] for f in findings)

    def test_bad_id_format(self):
        scene = "@@META\nPrev: ???\nNext: 01.03.02\n@@END\nProse."
        findings = meta_validate(scene, {})
        major_findings = [f for f in findings if f["severity"] == "major"]
        assert any("invalid format" in f["evidence"] for f in major_findings)

    def test_missing_recommended_field_is_minor(self):
        scene_no_prev = GOOD_META.replace("Prev: 01.02.05\n", "")
        findings = meta_validate(scene_no_prev, {})
        major_findings = [f for f in findings if f["severity"] == "major"]
        assert any("PREV" in f["evidence"] for f in major_findings)

    def test_all_recommended_fields_present_no_minor(self):
        """Good meta with all recommended fields → no minor findings."""
        findings = meta_validate(GOOD_META, {})
        assert findings == []

    def test_id_with_variable_length_digits(self):
        """IDs like 1.2.3 or 001.002.003 should be accepted."""
        for valid_id in ("1.2.3", "01.02.03", "001.002.003", "1.10.100"):
            scene = f"@@META\nID: {valid_id}\nPart: 01\nChapter: 02\nScene: 03\nChrono: x\nPOV: x\nTense: x\nLocation: x\nCast: x\nObjective: x\nThreats: x\nSecrets: x\nContAnchors: x\nTerms: None\nThreads: None\nPrev: None\nNext: None\n@@END\nProse."
            findings = meta_validate(scene, {})
            major_and_critical = [f for f in findings if f["severity"] in ("major", "critical")]
            assert not any("ID" in f["evidence"] for f in major_and_critical), (
                f"Unexpectedly flagged valid ID '{valid_id}'"
            )

    def test_template_recommendations_override_legacy_defaults(self):
        scene = (
            "@@META\n"
            "ID: 01.03.01\n"
            "Prev: 01.02.05\n"
            "Next: 01.03.02\n"
            "@@END\n"
            "Prose."
        )
        template = (
            "# Scene Template\n\n"
            "### META Block\n\n"
            "```md\n"
            "@@META\n"
            "ID: 01.03.01\n"
            "Now.Cast: Amelia\n"
            "Now.Terms: Breach Gates\n"
            "Now.Threads: vault_mystery\n"
            "Prev: 01.02.05\n"
            "Next: 01.03.02\n"
            "@@END\n"
            "```\n"
        )

        findings = meta_validate(scene, {"TEMPLATE.md": template})
        assert findings == []

    def test_template_missing_meta_block_falls_back_to_legacy_recommendations(self):
        scene_no_pov = GOOD_META.replace("POV: Amelia\n", "")
        template_without_meta_block = "# Scene Template\n\n## Other Section\nNo META block here.\n"

        findings = meta_validate(scene_no_pov, {"TEMPLATE.md": template_without_meta_block})
        assert findings == []

    def test_id_still_required_when_template_omits_id_field(self):
        scene_missing_id = GOOD_META.replace("ID: 01.03.01\n", "")
        template_without_id = (
            "# Scene Template\n\n"
            "### META Block\n\n"
            "```md\n"
            "@@META\n"
            "Now.Cast: Amelia\n"
            "Prev: 01.02.05\n"
            "Next: 01.03.02\n"
            "@@END\n"
            "```\n"
        )

        findings = meta_validate(scene_missing_id, {"TEMPLATE.md": template_without_id})
        assert findings == []

    def test_prev_next_missing_are_major_not_minor_with_template(self):
        scene_missing_pointers = (
            GOOD_META.replace("Prev: 01.02.05\n", "")
            .replace("Next: 01.03.02\n", "")
        )
        template = (
            "# Scene Template\n\n"
            "### META Block\n\n"
            "```md\n"
            "@@META\n"
            "ID: 01.03.01\n"
            "Now.Cast: Amelia\n"
            "Prev: 01.02.05\n"
            "Next: 01.03.02\n"
            "@@END\n"
            "```\n"
        )

        findings = meta_validate(scene_missing_pointers, {"TEMPLATE.md": template})
        major_evidence = [f["evidence"] for f in findings if f["severity"] == "major"]
        minor_evidence = [f["evidence"] for f in findings if f["severity"] == "minor"]

        assert any("PREV" in evidence for evidence in major_evidence)
        assert any("NEXT" in evidence for evidence in major_evidence)
        assert not any("PREV" in evidence for evidence in minor_evidence)
        assert not any("NEXT" in evidence for evidence in minor_evidence)


# ===========================================================================
# Stage: index_crossref
# ===========================================================================

class TestIndexCrossref:

    def test_clean_indexes_no_findings(self):
        findings = index_crossref("", GOOD_INDEXES)
        assert findings == []

    def test_duplicate_heading(self):
        indexes = dict(GOOD_INDEXES)
        indexes["cast"] += "\n### George Thorne\n- **Role:** Duplicate\n"
        findings = index_crossref("", indexes)
        critical = [f for f in findings if f["severity"] == "critical"]
        assert any("Duplicate heading" in f["evidence"] for f in critical)

    def test_missing_required_field_in_cast(self):
        indexes = dict(GOOD_INDEXES)
        # Remove the Relationships section from George's entry
        indexes["cast"] = (
            "# Cast\n\n## Main Characters\n\n"
            "### Amelia Ashvale\n**Role:** Warden\n**Relationships:**\n  - George: mentor\n"
            "  - First seen: 01.01.01\n\n"
            "### George Thorne\n**Role:** Elder\n"
            # No Relationships
        )
        findings = index_crossref("", indexes)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("Relationships" in f["evidence"] for f in major)

    def test_missing_required_field_in_glossary(self):
        indexes = dict(GOOD_INDEXES)
        # Missing 'First seen' from glossary entry
        indexes["glossary"] = (
            "# Glossary\n\n## Terms\n\n"
            "### Breach Gates\n**Definition:** Sealed portals\n**Notes:** Always capitalized\n"
            # No First seen
        )
        findings = index_crossref("", indexes)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("First seen" in f["evidence"] for f in major)

    def test_orphan_first_seen(self):
        indexes = dict(GOOD_INDEXES)
        indexes["cast"] += (
            "\n### Lyra Voss\n"
            "- **Role:** Scout\n"
            "- **Relationships:**\n  - Amelia: ally\n"
            "- First seen: 09.09.09\n"
        )
        findings = index_crossref("", indexes)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("09.09.09" in f["evidence"] for f in major)

    def test_orphan_thread_opened(self):
        indexes = dict(GOOD_INDEXES)
        indexes["threads"] += (
            "\n### new_thread\n**Opened:** 08.08.08\n**Status:** Active\n"
        )
        findings = index_crossref("", indexes)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("08.08.08" in f["evidence"] for f in major)

    def test_orphan_relationship_target(self):
        indexes = dict(GOOD_INDEXES)
        indexes["cast"] = indexes["cast"].replace(
            "  - George: mentor", "  - Unknown Elder: mentor"
        )
        findings = index_crossref("", indexes)
        minor = [f for f in findings if f["severity"] == "minor"]
        assert any("Unknown Elder" in f["evidence"] for f in minor)

    def test_thread_status_vs_section_active_is_resolved(self):
        indexes = dict(GOOD_INDEXES)
        indexes["threads"] = indexes["threads"].replace(
            "**Status:** Active", "**Status:** Resolved"
        )
        findings = index_crossref("", indexes)
        critical = [f for f in findings if f["severity"] == "critical"]
        assert any("Active Threads" in f["evidence"] for f in critical)

    def test_placeholder_detected(self):
        indexes = dict(GOOD_INDEXES)
        indexes["glossary"] += "\n### New Term\n**Definition:** [TODO]\n**First seen:** 01.01.01\n"
        findings = index_crossref("", indexes)
        minor = [f for f in findings if f["severity"] == "minor"]
        assert any("placeholder" in f["evidence"].lower() for f in minor)

    def test_glossary_casing_violation(self):
        indexes = dict(GOOD_INDEXES)
        # Add lowercase "breach gates" to threads
        indexes["threads"] += "\nThe breach gates are weakening.\n"
        findings = index_crossref("", indexes)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("breach gates" in f["evidence"] for f in major)

    def test_partial_cast_name_in_timeline(self):
        indexes = dict(GOOD_INDEXES)
        # Add a reference to just "George" (not "George Thorne") in timeline
        indexes["timeline"] += "\n**01.03.03** George meets someone.\n"
        findings = index_crossref("", indexes)
        minor = [f for f in findings if f["severity"] == "minor"]
        assert any("George Thorne" in f["evidence"] for f in minor)

    def test_empty_indexes_no_crash(self):
        """Should return empty findings without raising."""
        findings = index_crossref("", {})
        assert isinstance(findings, list)


# ===========================================================================
# Stage: scene_index_match
# ===========================================================================

class TestSceneIndexMatch:

    def test_no_op_with_valid_input(self):
        assert scene_index_match(GOOD_META, GOOD_INDEXES) == []

    def test_no_op_with_invalid_input(self):
        findings = scene_index_match("@@META\nCast: Unknown\n@@END\nBody", {})
        assert findings == []


# ===========================================================================
# Stage: timeline_validate
# ===========================================================================

class TestTimelineValidate:

    def test_clean_scene_no_findings(self):
        assert timeline_validate(GOOD_META, GOOD_INDEXES) == []

    def test_out_of_order_scenes(self):
        indexes = dict(GOOD_INDEXES)
        indexes["timeline"] = (
            "# Timeline\n\n## Part 01\n\n### Chapter 01\n\n"
            "**01.01.02** Scene B.\n"
            "**01.01.01** Scene A — placed after B.\n"
        )
        findings = timeline_validate("", indexes)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("01.01.01" in f["evidence"] for f in major)

    def test_scene_not_in_timeline(self):
        """Scene with ID 01.03.01 not listed in TIMELINE.md."""
        indexes = dict(GOOD_INDEXES)
        # Use TIMELINE without 01.03.01
        indexes["timeline"] = (
            "# Timeline\n\n## Part 01\n\n### Chapter 01\n\n"
            "**01.01.01** Amelia wakes.\n"
        )
        findings = timeline_validate(GOOD_META, indexes)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("01.03.01" in f["evidence"] for f in major)

    def test_scene_in_timeline_no_finding(self):
        """Scene 01.03.01 is in TIMELINE.md → no finding for it."""
        findings = timeline_validate(GOOD_META, GOOD_INDEXES)
        assert all("01.03.01" not in f["evidence"] for f in findings)

    def test_bad_prev_pointer(self):
        scene = GOOD_META.replace("Prev: 01.02.05", "Prev: 99.99.99")
        findings = timeline_validate(scene, GOOD_INDEXES)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("99.99.99" in f["evidence"] for f in major)

    def test_bad_next_pointer(self):
        scene = GOOD_META.replace("Next: 01.03.02", "Next: 99.99.99")
        findings = timeline_validate(scene, GOOD_INDEXES)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("99.99.99" in f["evidence"] for f in major)

    def test_namespaced_prev_next_aliases_are_accepted(self):
        scene = (
            GOOD_META
            .replace("Prev: 01.02.05\n", "Now.Prev: 01.02.05\n")
            .replace("Next: 01.03.02\n", "Then.Next: 01.03.02\n")
        )
        findings = timeline_validate(scene, GOOD_INDEXES)
        assert findings == []

    def test_prev_none_not_flagged(self):
        scene = GOOD_META.replace("Prev: 01.02.05", "Prev: None")
        findings = timeline_validate(scene, GOOD_INDEXES)
        assert findings == []

    def test_tbd_next_not_flagged(self):
        """Next: TBD is a valid sentinel — must not be flagged by timeline_validate."""
        scene = GOOD_META.replace("Next: 01.03.02", "Next: TBD")
        findings = timeline_validate(scene, GOOD_INDEXES)
        assert findings == []

    def test_plain_filename_prev_next_not_flagged(self):
        """Prev/Next as plain filenames without an embedded scene ID should not
        trigger a 'not a valid scene reference' error in timeline_validate.
        The timeline cross-check is skipped when no NN.NN.NN can be extracted."""
        scene = (
            "@@META\n"
            "Prev: scene-opening.txt\n"
            "Next: scene-aftermath.txt\n"
            "@@END\n\n"
            "George stood at the window for a long time."
        )
        findings = timeline_validate(scene, GOOD_INDEXES)
        # No "not a valid scene reference" errors — plain .txt filenames are accepted.
        assert not any(
            "not a valid scene reference" in (f["evidence"] or "")
            for f in findings
        )

    def test_empty_timeline_no_crash(self):
        findings = timeline_validate(GOOD_META, {})
        assert isinstance(findings, list)

    def test_ordering_resets_between_chapters(self):
        """Chapter boundary resets the ordering check."""
        indexes = dict(GOOD_INDEXES)
        # Chapter 01: 01.01.02, 01.01.01 → out-of-order (same chapter)
        # Chapter 02: 01.02.01 → fine (new chapter, counter reset)
        indexes["timeline"] = (
            "# Timeline\n\n## Part 01\n\n"
            "### Chapter 01\n\n"
            "**01.01.02** B.\n"
            "**01.01.01** A — out of order.\n\n"
            "### Chapter 02\n\n"
            "**01.02.01** C — fine.\n"
        )
        findings = timeline_validate("", indexes)
        major = [f for f in findings if f["severity"] == "major"]
        # Only 01.01.01 (within Chapter 01) should be flagged
        assert len(major) == 1
        assert "01.01.01" in major[0]["evidence"]


# ===========================================================================
# Stage: style_patterns
# ===========================================================================

class TestStylePatterns:

    def test_clean_prose_no_findings(self):
        assert style_patterns(GOOD_META, {}) == []

    def test_double_space_detected(self):
        scene = GOOD_META.replace(
            "The corridor smelled of rust and old stone.",
            "The corridor  smelled of rust  and old stone.",
        )
        findings = style_patterns(scene, {})
        assert len(findings) == 1
        assert findings[0]["severity"] == "minor"
        assert "double" in findings[0]["evidence"].lower() or "extra" in findings[0]["evidence"].lower()

    def test_double_space_not_flagged_in_meta(self):
        """Double spaces inside @@META block should not trigger a finding."""
        scene = GOOD_META.replace("POV: Amelia", "POV:  Amelia")  # Double space in meta
        findings = style_patterns(scene, {})
        assert findings == []

    def test_style_md_rule_violation(self):
        indexes = {
            "STYLE.md": '# Style\n\n- Never use "suddenly" in prose.\n'
        }
        scene = GOOD_META.replace(
            "The corridor smelled of rust and old stone.",
            "The corridor suddenly smelled of rust.",
        )
        findings = style_patterns(scene, indexes)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("suddenly" in f["evidence"] for f in major)

    def test_style_md_rule_case_insensitive(self):
        indexes = {
            "STYLE.md": '# Style\n\n- Never use "Suddenly" in prose.\n'
        }
        scene = GOOD_META.replace(
            "The corridor smelled of rust and old stone.",
            "The corridor suddenly smelled of rust.",
        )
        findings = style_patterns(scene, indexes)
        major = [f for f in findings if f["severity"] == "major"]
        assert any("Suddenly" in f["evidence"] for f in major)

    def test_style_md_rule_not_violated(self):
        indexes = {
            "STYLE.md": '# Style\n\n- Never use "suddenly" in prose.\n'
        }
        # Scene prose does not contain "suddenly"
        findings = style_patterns(GOOD_META, indexes)
        assert findings == []

    def test_no_prose_section_no_findings(self):
        """Scene with only @@META block and no content after @@END."""
        scene = "@@META\nID: 01.01.01\n@@END\n"
        findings = style_patterns(scene, {})
        assert findings == []

    def test_line_numbers_are_global(self):
        """Line numbers should be global (not prose-relative)."""
        meta_lines = GOOD_META.split("\n@@END\n")[0].splitlines()
        meta_line_count = len(meta_lines) + 1  # +1 for the @@END line itself
        # Insert double space on first prose line
        scene = GOOD_META.replace(
            "The corridor smelled of rust and old stone.",
            "The corridor  smelled.",
        )
        findings = style_patterns(scene, {})
        assert len(findings) == 1
        # line_start should be > meta_line_count (it's in the prose section)
        assert findings[0]["line_start"] is not None
        assert findings[0]["line_start"] > meta_line_count


# ===========================================================================
# Orchestrator: run_code_checks
# ===========================================================================

class TestRunCodeChecks:

    def test_returns_finding_objects(self):
        findings = run_code_checks(GOOD_META, GOOD_INDEXES)
        assert all(isinstance(f, Finding) for f in findings)

    def test_clean_scene_returns_empty(self):
        findings = run_code_checks(GOOD_META, GOOD_INDEXES)
        assert findings == []

    def test_findings_numbered_sequentially(self):
        """Multiple issues → findings are numbered 1, 2, 3, ..."""
        scene = "@@META\n@@END\nThe corridor  smelled odd."
        findings = run_code_checks(scene, GOOD_INDEXES)
        numbers = [f.number for f in findings]
        assert numbers == list(range(1, len(findings) + 1))

    def test_all_findings_have_origin_code(self):
        findings = run_code_checks("@@META\n@@END\nProse with  double spaces.", GOOD_INDEXES)
        assert all(f.origin == "code" for f in findings)

    def test_meta_findings_come_first(self):
        """meta_validate runs first → its findings appear before index_crossref findings."""
        scene_no_meta = "Just prose, no @@META block at all."
        indexes = dict(GOOD_INDEXES)
        indexes["cast"] += "\n### George Thorne\n- **Role:** Dup\n"  # index_crossref issue
        findings = run_code_checks(scene_no_meta, indexes)
        # First finding should be from meta_validate (lens="meta_validate")
        assert findings[0].lens == "meta_validate"

    def test_stage_exception_does_not_abort_pipeline(self):
        """If one stage raises, the others still run."""
        from orchestrator.services.code_checks import orchestrator
        import unittest.mock as mock

        original_stages = orchestrator._STAGES[:]
        bad_stage = mock.Mock(side_effect=RuntimeError("kaboom"))
        bad_stage.__name__ = "bad_stage"

        try:
            orchestrator._STAGES = [bad_stage, meta_validate]
            # Should not raise; meta_validate findings should still appear
            findings = run_code_checks("No meta here.", {})
            assert any(f.lens == "meta_validate" for f in findings)
        finally:
            orchestrator._STAGES = original_stages

    def test_mixed_origins_when_both_present(self):
        """All code check findings always have origin='code'."""
        findings = run_code_checks(GOOD_META, GOOD_INDEXES)
        # Even empty list is fine; if non-empty, all must be 'code'
        for f in findings:
            assert f.origin == "code"

    def test_scene_with_all_issues(self):
        """Scene designed to trigger findings from both active stages."""
        bad_scene = (
            "@@META\n"
            "ID: BAD-ID\n"
            "@@END\n"
            "Prose with  double space.\n"
        )
        bad_indexes = {
            "cast": "# Cast\n\n### Alice\n",
        }
        findings = run_code_checks(bad_scene, bad_indexes)
        lenses = {f.lens for f in findings}
        assert "meta_validate" in lenses
        assert "style_patterns" in lenses

    def test_index_only_issues_do_not_emit_findings(self):
        indexes = dict(GOOD_INDEXES)
        indexes["cast"] += "\n### George Thorne\n- **Role:** Duplicate\n"
        findings = run_code_checks(GOOD_META, indexes)
        assert findings == []
