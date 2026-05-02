"""Service layer for silence rules (Task C3).

Orchestrates SilenceRuleStore + SnapshotStore to create, manage, and apply
silence rules against snapshot findings.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from core.domain import SilenceRule, SnapshotFinding
from orchestrator.persistence.silence_rule_store import SilenceRuleStore
from orchestrator.persistence.snapshot_store import SnapshotStore


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_rule(
    conn: sqlite3.Connection,
    rule: SilenceRule,
    project_path: Path | None = None,
) -> SilenceRule:
    """Persist a new silence rule; returns the rule with ``id`` populated."""
    SilenceRuleStore.create(conn, rule, project_path=project_path)
    return rule


def get_rule(
    conn: sqlite3.Connection,
    rule_id: int,
    project_path: Path | None = None,
) -> Optional[SilenceRule]:
    """Return the silence rule with *rule_id*, or None if not found."""
    return SilenceRuleStore.get(conn, rule_id, project_path=project_path)


def list_rules(
    conn: sqlite3.Connection,
    project_path: Path | None = None,
    *,
    include_suspended: bool = True,
) -> list[SilenceRule]:
    """Return all silence rules (for the management UI)."""
    return SilenceRuleStore.list_all(
        conn, project_path=project_path, include_suspended=include_suspended
    )


def list_applicable_rules(
    conn: sqlite3.Connection,
    scene_path: str,
    project_path: Path | None = None,
) -> list[SilenceRule]:
    """Return active rules that can affect findings in *scene_path*.

    Combines scene-scoped rules for this scene with project-wide rules.
    Suspended rules are excluded.
    """
    return SilenceRuleStore.list_applicable(
        conn, scene_path, project_path=project_path
    )


def suspend_rule(
    conn: sqlite3.Connection,
    rule_id: int,
    suspended: bool,
    suspended_at: str = "",
    project_path: Path | None = None,
) -> Optional[SilenceRule]:
    """Set the suspended state of a silence rule.

    Returns the updated rule, or None if the rule doesn't exist.
    """
    existing = SilenceRuleStore.get(conn, rule_id, project_path=project_path)
    if existing is None:
        return None
    SilenceRuleStore.update_suspended(
        conn, rule_id, suspended=suspended, suspended_at=suspended_at
    )
    return SilenceRuleStore.get(conn, rule_id, project_path=project_path)


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    """Delete a silence rule by id.

    Returns True if the rule existed and was deleted, False if not found.
    """
    existing = SilenceRuleStore.get(conn, rule_id)
    if existing is None:
        return False
    SilenceRuleStore.delete(conn, rule_id)
    return True


# ---------------------------------------------------------------------------
# Applying rules to findings
# ---------------------------------------------------------------------------

def apply_silence_rules(
    rules: list[SilenceRule],
    findings: list[SnapshotFinding],
) -> list[SnapshotFinding]:
    """Return a copy of *findings* with silenced findings marked as such.

    This is a pure function — no DB access. The caller is responsible for
    persisting any state changes via ``persist_silenced_states``.

    Rules in *rules* must already be filtered to those applicable for the
    scene (via ``list_applicable_rules`` or equivalent).

    Only ``active`` findings are candidates for silencing. Resolved findings
    and already-silenced findings are left untouched.
    """
    if not rules:
        return findings

    result: list[SnapshotFinding] = []
    for finding in findings:
        if finding.state != "active":
            result.append(finding)
            continue
        if any(r.matches(finding) for r in rules):
            # Create a new SnapshotFinding with state="silenced" (slots=True
            # means we can't just assign — rebuild via from_dict).
            silenced = SnapshotFinding.from_dict({**finding.to_dict(), "state": "silenced"})
            result.append(silenced)
        else:
            result.append(finding)
    return result


def apply_and_persist_silence_rules(
    conn: sqlite3.Connection,
    scene_path: str,
    findings: list[SnapshotFinding],
    project_path: Path | None = None,
) -> list[SnapshotFinding]:
    """Apply silence rules and persist updated states to ``snapshot_finding``.

    Returns the updated findings list. Findings whose state was changed to
    ``silenced`` are also written back to the DB.
    """
    rules = SilenceRuleStore.list_applicable(
        conn, scene_path, project_path=project_path
    )
    updated = apply_silence_rules(rules, findings)

    # Persist any state changes.
    for original, new_f in zip(findings, updated):
        if original.state != new_f.state and new_f.id is not None:
            SnapshotStore.update_finding_state(conn, new_f.id, new_f.state)

    return updated


__all__ = [
    "create_rule",
    "get_rule",
    "list_rules",
    "list_applicable_rules",
    "suspend_rule",
    "delete_rule",
    "apply_silence_rules",
    "apply_and_persist_silence_rules",
]
