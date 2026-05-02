"""Tests for silence rule service (Task C3)."""

import sqlite3

from core.domain import AnalysisSnapshot, SilenceRule, SnapshotFinding
from orchestrator.persistence.database import init_db
from orchestrator.persistence.snapshot_store import SnapshotStore
from orchestrator.services.silence_rule_service import (
    apply_and_persist_silence_rules,
    apply_silence_rules,
    create_rule,
    delete_rule,
    get_rule,
    list_applicable_rules,
    list_rules,
    suspend_rule,
)


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
        number=1,
        severity="moderate",
        lens="prose",
        location="paragraph 3",
        line_start=10,
        scene_path="text/ch1.md",
        evidence="The sentence is too long and winding.",
        state="active",
    )
    defaults.update(kwargs)
    return SnapshotFinding(**defaults)


def _instance_rule(finding_id: int = 1) -> SilenceRule:
    return SilenceRule(
        rule_type="instance",
        scope="scene",
        scene_path="text/ch1.md",
        finding_id=finding_id,
        created_at="2026-04-13T10:00:00",
    )


def _pattern_rule() -> SilenceRule:
    return SilenceRule(
        rule_type="pattern",
        scope="scene",
        scene_path="text/ch1.md",
        lens="prose",
        severity="",
        text_pattern="too long",
        created_at="2026-04-13T10:00:00",
    )


def _category_rule() -> SilenceRule:
    return SilenceRule(
        rule_type="category",
        scope="project",
        lens="prose",
        created_at="2026-04-13T10:00:00",
    )


def _persist_snapshot_with_findings(
    conn: sqlite3.Connection,
    findings: list[SnapshotFinding],
) -> AnalysisSnapshot:
    """Save a snapshot + findings so they have DB ids."""
    snap = AnalysisSnapshot(
        scene_paths=["text/ch1.md"],
        depth_mode="quick",
        scene_hashes={"text/ch1.md": "abc"},
        created_at="2026-04-13T10:00:00",
        findings=findings,
    )
    SnapshotStore.create(conn, snap)
    return snap


# ---------------------------------------------------------------------------
# CRUD service tests
# ---------------------------------------------------------------------------

def test_create_rule_sets_id():
    conn = _conn()
    rule = _instance_rule()
    assert rule.id is None
    result = create_rule(conn, rule)
    assert result.id is not None


def test_get_rule_returns_persisted_rule():
    conn = _conn()
    rule = _instance_rule()
    create_rule(conn, rule)
    loaded = get_rule(conn, rule.id)
    assert loaded is not None
    assert loaded.rule_type == "instance"
    assert loaded.finding_id == 1


def test_get_rule_nonexistent_returns_none():
    conn = _conn()
    assert get_rule(conn, 9999) is None


def test_list_rules_returns_all():
    conn = _conn()
    create_rule(conn, _instance_rule())
    create_rule(conn, _pattern_rule())
    create_rule(conn, _category_rule())
    rules = list_rules(conn)
    assert len(rules) == 3


def test_list_applicable_rules_combines_scene_and_project():
    conn = _conn()
    create_rule(conn, _instance_rule())     # scene-scoped for ch1
    create_rule(conn, _category_rule())     # project-wide
    create_rule(conn, SilenceRule(          # scene-scoped for ch2 (should not appear)
        rule_type="instance",
        scope="scene",
        scene_path="text/ch2.md",
        finding_id=99,
        created_at="2026-04-13T10:00:00",
    ))

    applicable = list_applicable_rules(conn, "text/ch1.md")
    assert len(applicable) == 2


def test_suspend_rule_true():
    conn = _conn()
    rule = _instance_rule()
    create_rule(conn, rule)

    updated = suspend_rule(conn, rule.id, suspended=True, suspended_at="2026-04-14T00:00:00")
    assert updated is not None
    assert updated.suspended is True
    assert updated.suspended_at == "2026-04-14T00:00:00"


def test_suspend_rule_nonexistent_returns_none():
    conn = _conn()
    result = suspend_rule(conn, 9999, suspended=True)
    assert result is None


def test_suspend_and_unsuspend_rule():
    conn = _conn()
    rule = _instance_rule()
    create_rule(conn, rule)

    suspend_rule(conn, rule.id, suspended=True, suspended_at="2026-04-14T00:00:00")
    reactivated = suspend_rule(conn, rule.id, suspended=False)
    assert reactivated.suspended is False


def test_delete_rule_returns_true():
    conn = _conn()
    rule = _instance_rule()
    create_rule(conn, rule)
    assert delete_rule(conn, rule.id) is True
    assert get_rule(conn, rule.id) is None


def test_delete_rule_nonexistent_returns_false():
    conn = _conn()
    assert delete_rule(conn, 9999) is False


# ---------------------------------------------------------------------------
# apply_silence_rules (pure function) tests
# ---------------------------------------------------------------------------

def test_apply_silence_rules_no_rules_leaves_findings_unchanged():
    findings = [_make_finding(number=1), _make_finding(number=2)]
    result = apply_silence_rules([], findings)
    assert all(f.state == "active" for f in result)
    assert len(result) == 2


def test_apply_silence_rules_instance_silences_matching_finding():
    finding_active = _make_finding(id=42, number=1)
    finding_other = _make_finding(id=99, number=2)
    rule = SilenceRule(rule_type="instance", scope="scene", finding_id=42, created_at="ts")
    result = apply_silence_rules([rule], [finding_active, finding_other])
    assert result[0].state == "silenced"
    assert result[1].state == "active"


def test_apply_silence_rules_category_silences_all_matching_lens():
    f1 = _make_finding(number=1, lens="prose")
    f2 = _make_finding(number=2, lens="pacing")
    rule = SilenceRule(rule_type="category", scope="project", lens="prose", created_at="ts")
    result = apply_silence_rules([rule], [f1, f2])
    assert result[0].state == "silenced"
    assert result[1].state == "active"


def test_apply_silence_rules_pattern_matches_text():
    f1 = _make_finding(number=1, lens="prose", evidence="sentence too long")
    f2 = _make_finding(number=2, lens="prose", evidence="concise evidence")
    rule = SilenceRule(
        rule_type="pattern", scope="scene",
        lens="prose", text_pattern="too long", created_at="ts"
    )
    result = apply_silence_rules([rule], [f1, f2])
    assert result[0].state == "silenced"
    assert result[1].state == "active"


def test_apply_silence_rules_already_silenced_stays_silenced():
    finding = _make_finding(number=1, state="silenced")
    rule = SilenceRule(rule_type="category", scope="project", lens="prose", created_at="ts")
    result = apply_silence_rules([rule], [finding])
    assert result[0].state == "silenced"  # unchanged


def test_apply_silence_rules_resolved_not_touched():
    finding = _make_finding(number=1, state="resolved")
    rule = SilenceRule(rule_type="category", scope="project", lens="prose", created_at="ts")
    result = apply_silence_rules([rule], [finding])
    assert result[0].state == "resolved"  # unchanged


def test_apply_silence_rules_returns_new_objects():
    """The original finding objects must not be mutated."""
    original = _make_finding(id=1, number=1)
    rule = SilenceRule(rule_type="instance", scope="scene", finding_id=1, created_at="ts")
    result = apply_silence_rules([rule], [original])
    # Original is untouched.
    assert original.state == "active"
    # Returned copy is silenced.
    assert result[0].state == "silenced"


# ---------------------------------------------------------------------------
# apply_and_persist_silence_rules (DB integration) tests
# ---------------------------------------------------------------------------

def test_apply_and_persist_silence_rules_updates_db():
    conn = _conn()
    f = _make_finding(number=1)
    snap = _persist_snapshot_with_findings(conn, [f])
    # Get the DB-aware finding with id.
    loaded_snap = SnapshotStore.get(conn, snap.id)
    db_finding = loaded_snap.findings[0]
    assert db_finding.state == "active"

    # Create a rule that matches.
    rule = create_rule(conn, SilenceRule(
        rule_type="category",
        scope="project",
        lens="prose",
        created_at="2026-04-13T10:00:00",
    ))

    updated = apply_and_persist_silence_rules(
        conn, "text/ch1.md", [db_finding]
    )
    assert updated[0].state == "silenced"

    # Verify state was written to DB.
    reloaded = SnapshotStore.get(conn, snap.id)
    assert reloaded.findings[0].state == "silenced"


def test_apply_and_persist_silence_rule_suspend_and_reappear():
    """Create rule → finding silenced. Suspend rule → finding reappears."""
    conn = _conn()
    f = _make_finding(number=1)
    snap = _persist_snapshot_with_findings(conn, [f])
    db_finding = SnapshotStore.get(conn, snap.id).findings[0]

    # Create a matching rule.
    rule = create_rule(conn, SilenceRule(
        rule_type="category",
        scope="project",
        lens="prose",
        created_at="2026-04-13T10:00:00",
    ))

    # Apply: finding should be silenced.
    silenced = apply_and_persist_silence_rules(conn, "text/ch1.md", [db_finding])
    assert silenced[0].state == "silenced"

    # Suspend the rule.
    suspend_rule(conn, rule.id, suspended=True, suspended_at="2026-04-14T00:00:00")

    # Reset finding state back to active in DB for re-test.
    SnapshotStore.update_finding_state(conn, db_finding.id, "active")
    db_finding_reset = SnapshotStore.get(conn, snap.id).findings[0]
    assert db_finding_reset.state == "active"

    # Re-apply: rule is suspended, so finding should remain active.
    reapplied = apply_and_persist_silence_rules(conn, "text/ch1.md", [db_finding_reset])
    assert reapplied[0].state == "active"
