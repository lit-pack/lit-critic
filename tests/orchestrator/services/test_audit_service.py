"""Tests for orchestrator.services.audit_service."""

from __future__ import annotations

from types import SimpleNamespace
import pytest

from orchestrator.runtime.models import Finding
from orchestrator.services.audit_service import (
    AuditReport,
    audit_scene,
    audit_indexes_deterministic,
    audit_indexes_semantic,
    format_audit_report,
)


def _base_indexes() -> dict[str, str]:
    return {
        "CANON.md": "# Canon\n\n## Rules\n\nMagic is blocked in sanctuaries.\n",
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
            "**01.01.02** Amelia searches.\n"
        ),
    }


def _finding_ids(report) -> set[str]:
    return {f.check_id for f in report.deterministic}


def test_deterministic_orphan_first_seen():
    indexes = _base_indexes()
    indexes["cast"] += (
        "\n### Lyra Voss\n"
        "- **Role:** Scout\n"
        "- **Relationships:**\n"
        "  - Amelia: ally\n"
        "- **Key facts:**\n"
        "  - First seen: 09.09.09\n"
    )
    report = audit_indexes_deterministic(indexes)
    assert "orphan_first_seen" in _finding_ids(report)


def test_deterministic_orphan_thread_opened():
    indexes = _base_indexes()
    indexes["threads"] += (
        "\n### war_secret\n"
        "**Opened:** 08.08.08\n"
        "**Status:** Active\n"
    )
    report = audit_indexes_deterministic(indexes)
    assert "orphan_thread_opened" in _finding_ids(report)


def test_deterministic_orphan_relationship_target():
    indexes = _base_indexes()
    indexes["cast"] = indexes["cast"].replace("George: mentor", "Unknown Elder: mentor")
    report = audit_indexes_deterministic(indexes)
    assert "orphan_relationship_target" in _finding_ids(report)


def test_deterministic_thread_status_vs_section():
    indexes = _base_indexes()
    indexes["threads"] = indexes["threads"].replace("**Status:** Active", "**Status:** Resolved")
    report = audit_indexes_deterministic(indexes)
    assert "thread_status_vs_section" in _finding_ids(report)


def test_deterministic_timeline_scene_ordering():
    indexes = _base_indexes()
    indexes["timeline"] = (
        "# Timeline\n\n"
        "## Part 01\n\n"
        "### Chapter 01\n\n"
        "**01.01.02** Later scene first.\n"
        "**01.01.01** Earlier scene second.\n"
    )
    report = audit_indexes_deterministic(indexes)
    assert "timeline_scene_ordering" in _finding_ids(report)


def test_deterministic_duplicate_heading_and_missing_required_fields_and_placeholder_census():
    indexes = _base_indexes()
    indexes["cast"] += "\n### George Thorne\n- **Role:** Elder\n"
    indexes["glossary"] += "\n### New Term\n**Definition:** [TODO]\n"

    report = audit_indexes_deterministic(indexes)
    ids = _finding_ids(report)
    assert "duplicate_heading" in ids
    assert "missing_required_fields" in ids
    assert report.placeholder_census["glossary"] >= 1


def test_deterministic_glossary_term_casing_and_cast_name_partial_usage():
    indexes = _base_indexes()
    indexes["threads"] += "\nBreach gates are weakening.\n"
    indexes["timeline"] += "\n**01.01.03** George meets Amelia in secret.\n"

    report = audit_indexes_deterministic(indexes)
    ids = _finding_ids(report)
    assert "glossary_term_casing" in ids
    assert "cast_name_in_other_files" in ids


@pytest.mark.asyncio
async def test_semantic_audit_maps_tool_output(mock_anthropic_client):
    mock_anthropic_client.create_message_with_tool.return_value.tool_input = {
        "contradictions": [
            {
                "file_a": "CANON.md",
                "location_a": "### George Thorne",
                "claim_a": "George is 56",
                "file_b": "CANON.md",
                "location_b": "## Historical Constraints",
                "claim_b": "War ended 12 years ago",
                "explanation": "The timeline arithmetic is inconsistent.",
                "severity": "error",
            }
        ]
    }
    findings = await audit_indexes_semantic(_base_indexes(), mock_anthropic_client)
    assert len(findings) == 1
    assert findings[0].check_id == "semantic_contradiction"
    assert findings[0].severity == "error"
    assert "Claim 1" in findings[0].message


def test_format_audit_report_includes_sections_and_summary():
    report = AuditReport(
        deterministic=[],
        semantic=[],
        placeholder_census={"cast": 2, "glossary": 1},
    )
    text = format_audit_report(report)
    assert "Index Audit Report" in text
    assert "Placeholder census" in text
    assert "Summary:" in text


@pytest.mark.asyncio
async def test_scene_audit_quick_returns_deterministic_only(monkeypatch):
    deterministic = [
        Finding(
            number=1,
            severity="minor",
            lens="code",
            location="line 1",
            evidence="Missing field",
            impact="Continuity gap",
            options=["Add field"],
            origin="code",
        )
    ]
    monkeypatch.setattr(
        "orchestrator.services.audit_service.run_code_checks",
        lambda _scene_text, _indexes: deterministic,
    )

    result = await audit_scene("@@META\nID: 01.01.01\n", _base_indexes(), deep=False)

    assert result["deterministic"] == deterministic
    assert result["semantic"] == []
    assert result["deep"] is False
    assert result["deep_error"] is None


@pytest.mark.asyncio
async def test_scene_audit_deep_adds_semantic_findings(monkeypatch):
    monkeypatch.setattr(
        "orchestrator.services.audit_service.run_code_checks",
        lambda _scene_text, _indexes: [],
    )

    async def _fake_run_lens(*_args, **_kwargs):
        return SimpleNamespace(
            findings=[
                {
                    "severity": "major",
                    "lens": "continuity",
                    "location": "Paragraph 2",
                    "evidence": "Timeline inconsistency",
                    "impact": "Reader confusion",
                    "options": ["Clarify timeline"],
                }
            ],
            error=None,
        )

    monkeypatch.setattr("orchestrator.services.audit_service.run_lens", _fake_run_lens)

    result = await audit_scene(
        "@@META\nID: 01.01.01\n",
        _base_indexes(),
        deep=True,
        client=object(),
        model="sonnet",
        max_tokens=123,
    )

    assert len(result["semantic"]) == 1
    assert result["semantic"][0].origin == "critic"
    assert result["semantic"][0].lens == "continuity"
    assert result["deep_error"] is None


@pytest.mark.asyncio
async def test_scene_audit_deep_failure_returns_deterministic_with_deep_error(monkeypatch):
    deterministic = [
        Finding(
            number=1,
            severity="minor",
            lens="code",
            location="line 4",
            evidence="Mismatch",
            impact="Audit noise",
            options=["Fix index"],
            origin="code",
        )
    ]
    monkeypatch.setattr(
        "orchestrator.services.audit_service.run_code_checks",
        lambda _scene_text, _indexes: deterministic,
    )

    async def _failing_run_lens(*_args, **_kwargs):
        return SimpleNamespace(findings=[], error="Deep provider timeout")

    monkeypatch.setattr("orchestrator.services.audit_service.run_lens", _failing_run_lens)

    result = await audit_scene(
        "@@META\nID: 01.01.01\n",
        _base_indexes(),
        deep=True,
        client=object(),
    )

    assert result["deterministic"] == deterministic
    assert result["semantic"] == []
    assert "Deep provider timeout" in (result["deep_error"] or "")
