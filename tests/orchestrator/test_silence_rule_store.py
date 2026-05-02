"""Tests for SilenceRule model and SilenceRuleStore (Task C2)."""

import sqlite3

from core.domain import SilenceRule, SnapshotFinding, SILENCE_RULE_TYPES, SILENCE_RULE_SCOPES
from orchestrator.persistence.database import init_db
from orchestrator.persistence.silence_rule_store import SilenceRuleStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _make_finding(**kwargs) -> SnapshotFinding:
    defaults = dict(
        id=1,
        snapshot_id=1,
        number=1,
        severity="moderate",
        lens="prose",
        location="paragraph 3",
        line_start=10,
        evidence="The sentence is too long and winding.",
        state="active",
    )
    defaults.update(kwargs)
    return SnapshotFinding(**defaults)


def _instance_rule(**kwargs) -> SilenceRule:
    defaults = dict(
        rule_type="instance",
        scope="scene",
        scene_path="text/ch1.md",
        finding_id=1,
        created_at="2026-04-13T10:00:00",
    )
    defaults.update(kwargs)
    return SilenceRule(**defaults)


def _pattern_rule(**kwargs) -> SilenceRule:
    defaults = dict(
        rule_type="pattern",
        scope="scene",
        scene_path="text/ch1.md",
        lens="prose",
        severity="moderate",
        text_pattern="too long",
        created_at="2026-04-13T10:00:00",
    )
    defaults.update(kwargs)
    return SilenceRule(**defaults)


def _category_rule(**kwargs) -> SilenceRule:
    defaults = dict(
        rule_type="category",
        scope="project",
        lens="prose",
        created_at="2026-04-13T10:00:00",
    )
    defaults.update(kwargs)
    return SilenceRule(**defaults)


# ---------------------------------------------------------------------------
# Domain model tests
# ---------------------------------------------------------------------------

def test_silence_rule_type_constants():
    assert "instance" in SILENCE_RULE_TYPES
    assert "pattern" in SILENCE_RULE_TYPES
    assert "category" in SILENCE_RULE_TYPES


def test_silence_rule_scope_constants():
    assert "scene" in SILENCE_RULE_SCOPES
    assert "project" in SILENCE_RULE_SCOPES


def test_silence_rule_from_dict_round_trip():
    rule = _instance_rule(note="ignore this one", suspended=False)
    d = rule.to_dict()
    rule2 = SilenceRule.from_dict(d)
    assert rule2.rule_type == "instance"
    assert rule2.finding_id == 1
    assert rule2.note == "ignore this one"
    assert rule2.suspended is False


# ---------------------------------------------------------------------------
# SilenceRule.matches() tests
# ---------------------------------------------------------------------------

def test_instance_rule_matches_by_finding_id():
    rule = _instance_rule(finding_id=42)
    finding = _make_finding(id=42)
    assert rule.matches(finding) is True


def test_instance_rule_no_match_different_id():
    rule = _instance_rule(finding_id=42)
    finding = _make_finding(id=99)
    assert rule.matches(finding) is False


def test_instance_rule_no_match_none_finding_id():
    rule = _instance_rule(finding_id=None)
    finding = _make_finding(id=42)
    assert rule.matches(finding) is False


def test_category_rule_matches_by_lens():
    rule = _category_rule(lens="prose")
    finding = _make_finding(lens="prose")
    assert rule.matches(finding) is True


def test_category_rule_no_match_different_lens():
    rule = _category_rule(lens="prose")
    finding = _make_finding(lens="pacing")
    assert rule.matches(finding) is False


def test_pattern_rule_matches_lens_only():
    rule = _pattern_rule(severity="", text_pattern="")
    finding = _make_finding(lens="prose", severity="minor")
    assert rule.matches(finding) is True


def test_pattern_rule_matches_lens_and_severity():
    rule = _pattern_rule(lens="prose", severity="moderate", text_pattern="")
    finding = _make_finding(lens="prose", severity="moderate")
    assert rule.matches(finding) is True


def test_pattern_rule_no_match_wrong_severity():
    rule = _pattern_rule(lens="prose", severity="major", text_pattern="")
    finding = _make_finding(lens="prose", severity="moderate")
    assert rule.matches(finding) is False


def test_pattern_rule_matches_text_pattern_in_evidence():
    rule = _pattern_rule(lens="prose", severity="", text_pattern="too long")
    finding = _make_finding(lens="prose", evidence="The sentence is too long and winding.")
    assert rule.matches(finding) is True


def test_pattern_rule_matches_text_pattern_in_location():
    rule = _pattern_rule(lens="prose", severity="", text_pattern="paragraph 3")
    finding = _make_finding(lens="prose", location="paragraph 3", evidence="Some evidence.")
    assert rule.matches(finding) is True


def test_pattern_rule_text_pattern_case_insensitive():
    rule = _pattern_rule(lens="prose", severity="", text_pattern="TOO LONG")
    finding = _make_finding(lens="prose", evidence="The sentence is too long.")
    assert rule.matches(finding) is True


def test_pattern_rule_no_match_text_pattern_absent():
    rule = _pattern_rule(lens="prose", severity="", text_pattern="contrived example")
    finding = _make_finding(lens="prose", evidence="The sentence is too long.")
    assert rule.matches(finding) is False


# ---------------------------------------------------------------------------
# SilenceRuleStore persistence tests
# ---------------------------------------------------------------------------

def test_silence_rule_store_create_and_get_instance():
    conn = _conn()
    rule = _instance_rule()
    rule_id = SilenceRuleStore.create(conn, rule)
    assert rule_id is not None
    assert rule.id == rule_id

    loaded = SilenceRuleStore.get(conn, rule_id)
    assert loaded is not None
    assert loaded.rule_type == "instance"
    assert loaded.finding_id == 1
    assert loaded.scope == "scene"
    assert loaded.suspended is False


def test_silence_rule_store_create_and_get_pattern():
    conn = _conn()
    rule = _pattern_rule(note="dialect in dialogue")
    rule_id = SilenceRuleStore.create(conn, rule)

    loaded = SilenceRuleStore.get(conn, rule_id)
    assert loaded is not None
    assert loaded.rule_type == "pattern"
    assert loaded.lens == "prose"
    assert loaded.text_pattern == "too long"
    assert loaded.note == "dialect in dialogue"


def test_silence_rule_store_create_and_get_category():
    conn = _conn()
    rule = _category_rule()
    rule_id = SilenceRuleStore.create(conn, rule)

    loaded = SilenceRuleStore.get(conn, rule_id)
    assert loaded is not None
    assert loaded.rule_type == "category"
    assert loaded.scope == "project"
    assert loaded.lens == "prose"


def test_silence_rule_store_get_nonexistent():
    conn = _conn()
    result = SilenceRuleStore.get(conn, 9999)
    assert result is None


def test_silence_rule_store_list_for_scene():
    conn = _conn()
    # Two scene-scoped rules for ch1, one for ch2, one project-wide.
    SilenceRuleStore.create(conn, _instance_rule(scene_path="text/ch1.md", finding_id=1))
    SilenceRuleStore.create(conn, _pattern_rule(scene_path="text/ch1.md"))
    SilenceRuleStore.create(conn, _instance_rule(scene_path="text/ch2.md", finding_id=2))
    SilenceRuleStore.create(conn, _category_rule())

    ch1_rules = SilenceRuleStore.list_for_scene(conn, "text/ch1.md")
    assert len(ch1_rules) == 2
    assert all(r.scope == "scene" for r in ch1_rules)
    assert all(r.scene_path == "text/ch1.md" for r in ch1_rules)


def test_silence_rule_store_list_project_wide():
    conn = _conn()
    SilenceRuleStore.create(conn, _instance_rule())
    SilenceRuleStore.create(conn, _category_rule())
    SilenceRuleStore.create(conn, _category_rule(lens="pacing"))

    project_rules = SilenceRuleStore.list_project_wide(conn)
    assert len(project_rules) == 2
    assert all(r.scope == "project" for r in project_rules)


def test_silence_rule_store_list_applicable_combines_both():
    conn = _conn()
    SilenceRuleStore.create(conn, _instance_rule(scene_path="text/ch1.md"))
    SilenceRuleStore.create(conn, _pattern_rule(scene_path="text/ch2.md"))  # other scene
    SilenceRuleStore.create(conn, _category_rule())  # project-wide

    applicable = SilenceRuleStore.list_applicable(conn, "text/ch1.md")
    # instance (ch1) + category (project), NOT pattern (ch2)
    assert len(applicable) == 2
    types = {r.rule_type for r in applicable}
    assert "instance" in types
    assert "category" in types


def test_silence_rule_store_update_suspended():
    conn = _conn()
    rule = _instance_rule()
    SilenceRuleStore.create(conn, rule)

    SilenceRuleStore.update_suspended(
        conn, rule.id, suspended=True, suspended_at="2026-04-14T08:00:00"
    )

    loaded = SilenceRuleStore.get(conn, rule.id)
    assert loaded.suspended is True
    assert loaded.suspended_at == "2026-04-14T08:00:00"


def test_silence_rule_store_list_for_scene_excludes_suspended_by_default():
    conn = _conn()
    active = _instance_rule(finding_id=1)
    suspended_rule = _instance_rule(finding_id=2, suspended=True)
    SilenceRuleStore.create(conn, active)
    SilenceRuleStore.create(conn, suspended_rule)

    rules = SilenceRuleStore.list_for_scene(conn, "text/ch1.md")
    assert len(rules) == 1
    assert rules[0].finding_id == 1


def test_silence_rule_store_list_for_scene_includes_suspended_when_requested():
    conn = _conn()
    active = _instance_rule(finding_id=1)
    susp = _instance_rule(finding_id=2, suspended=True)
    SilenceRuleStore.create(conn, active)
    SilenceRuleStore.create(conn, susp)

    rules = SilenceRuleStore.list_for_scene(
        conn, "text/ch1.md", include_suspended=True
    )
    assert len(rules) == 2


def test_silence_rule_store_delete():
    conn = _conn()
    rule = _instance_rule()
    SilenceRuleStore.create(conn, rule)

    SilenceRuleStore.delete(conn, rule.id)

    assert SilenceRuleStore.get(conn, rule.id) is None


def test_silence_rule_store_list_all():
    conn = _conn()
    SilenceRuleStore.create(conn, _instance_rule())
    SilenceRuleStore.create(conn, _pattern_rule())
    SilenceRuleStore.create(conn, _category_rule())

    all_rules = SilenceRuleStore.list_all(conn)
    assert len(all_rules) == 3


def test_silence_rule_store_list_all_exclude_suspended():
    conn = _conn()
    SilenceRuleStore.create(conn, _instance_rule())
    SilenceRuleStore.create(conn, _instance_rule(finding_id=2, suspended=True))

    active_only = SilenceRuleStore.list_all(conn, include_suspended=False)
    assert len(active_only) == 1
    assert active_only[0].suspended is False
