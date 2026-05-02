"""Snapshot analysis service — adapts analysis results to the new snapshot model (Task C6).

This is the glue layer between the existing analysis pipeline (which produces
``CoreFinding`` objects) and the new read-only feedback model (which stores
``AnalysisSnapshot`` objects).

The existing core analysis pipeline is **not modified**.  Instead, this service
wraps its output in an ``AnalysisSnapshot`` with finding correlation and
silence-rule filtering applied.

Usage
-----
After running the existing analysis pipeline and obtaining a ``list[CoreFinding]``,
call ``create_snapshot_from_core_findings`` to persist a correlated, filtered
snapshot.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.domain import AnalysisSnapshot, CoreFinding, SnapshotFinding
from orchestrator.persistence.snapshot_store import SnapshotStore
from orchestrator.persistence.path_utils import to_relative
from orchestrator.services.silence_rule_service import apply_and_persist_silence_rules


# ---------------------------------------------------------------------------
# CoreFinding → SnapshotFinding conversion
# ---------------------------------------------------------------------------

def core_finding_to_snapshot_finding(
    finding: CoreFinding,
    *,
    number: int,
    scene_path: str,
) -> SnapshotFinding:
    """Convert a ``CoreFinding`` to a ``SnapshotFinding``.

    The ``CoreFinding`` may carry interactive-session state (status, author_response,
    discussion_turns, revision_history) which is discarded.  The new model uses
    only: active, silenced, resolved.
    """
    from core.domain import SnapshotFinding
    f = SnapshotFinding(
        number=number,
        severity=finding.severity,
        lens=finding.lens,
        location=finding.location,
        line_start=finding.line_start,
        line_end=finding.line_end,
        scene_path=scene_path,
        evidence=finding.evidence,
        impact=finding.impact,
        options=list(finding.options),
        flagged_by=list(finding.flagged_by),
        ambiguity_type=finding.ambiguity_type,
        state="active",
    )
    # Compute correlation key immediately.
    correlation_key = SnapshotFinding.build_correlation_key(
        scene_path, f.lens, f.line_start, f.evidence
    )
    return SnapshotFinding.from_dict({**f.to_dict(), "correlation_key": correlation_key})


def core_findings_to_snapshot_findings(
    findings: list[CoreFinding],
    *,
    scene_path: str,
) -> list[SnapshotFinding]:
    """Convert a list of ``CoreFinding`` objects to ``SnapshotFinding`` objects."""
    return [
        core_finding_to_snapshot_finding(f, number=i + 1, scene_path=scene_path)
        for i, f in enumerate(findings)
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def create_snapshot_from_core_findings(
    conn: sqlite3.Connection,
    scene_paths: list[str],
    findings_by_scene: dict[str, list[CoreFinding]],
    *,
    depth_mode: str = "quick",
    scene_hashes: dict[str, str] | None = None,
    index_context_hash: str = "",
    frontier_model: str = "",
    checker_model: str = "",
    quick_model: str = "",
    project_path: Path | None = None,
    created_at: str = "",
    apply_silence: bool = True,
) -> AnalysisSnapshot:
    """Create and persist an ``AnalysisSnapshot`` from raw ``CoreFinding`` results.

    This is the primary entry point for adapting the existing analysis pipeline
    output into the new read-only snapshot model.

    Steps
    -----
    1. Convert ``CoreFinding`` → ``SnapshotFinding`` for each scene.
    2. Apply cross-run correlation (carry over silenced states, mark resolved).
    3. Apply silence rules (mark findings as silenced per the author's rules).
    4. Persist the snapshot and all findings to the DB.
    5. Return the persisted ``AnalysisSnapshot``.

    Args:
        conn:               Open DB connection.
        scene_paths:        Ordered list of scene paths analysed.
        findings_by_scene:  ``{scene_path: [CoreFinding, ...]}`` — analysis results.
        depth_mode:         ``"quick"`` or ``"deep"``.
        scene_hashes:       ``{scene_path: hash}`` at analysis time.
        index_context_hash: Hash of the index context used.
        frontier_model:     Model used for frontier lenses.
        checker_model:      Model used for checker lenses.
        quick_model:        Model used for quick lenses.
        project_path:       Project root for path relativisation.
        created_at:         ISO-8601 timestamp; defaults to now (UTC).
        apply_silence:      Whether to apply silence rules (default: True).
    """
    if not created_at:
        created_at = datetime.now(timezone.utc).isoformat()

    if scene_hashes is None:
        scene_hashes = {}

    rel_scene_paths = [to_relative(project_path, p) for p in scene_paths]
    rel_scene_hashes = {to_relative(project_path, k): v for k, v in scene_hashes.items()}

    # --- Convert all CoreFindings to SnapshotFindings ---
    all_findings: list[SnapshotFinding] = []
    global_number = 1
    for scene_path, rel_scene_path in zip(scene_paths, rel_scene_paths):
        core_fs = findings_by_scene.get(scene_path, [])
        for cf in core_fs:
            sf = core_finding_to_snapshot_finding(
                cf, number=global_number, scene_path=rel_scene_path
            )
            all_findings.append(sf)
            global_number += 1

    # --- Persist the snapshot ---
    snapshot = AnalysisSnapshot(
        scene_paths=rel_scene_paths,
        depth_mode=depth_mode,
        frontier_model=frontier_model,
        checker_model=checker_model,
        quick_model=quick_model,
        scene_hashes=rel_scene_hashes,
        index_context_hash=index_context_hash,
        created_at=created_at,
        findings=all_findings,
    )
    SnapshotStore.create(conn, snapshot, project_path=project_path)

    # --- Apply silence rules and persist updated states ---
    if apply_silence and rel_scene_paths:
        for rel_scene_path in rel_scene_paths:
            scene_findings = [f for f in snapshot.findings if f.scene_path == rel_scene_path]
            updated = apply_and_persist_silence_rules(
                conn, rel_scene_path, scene_findings, project_path=project_path
            )
            # Update the in-memory snapshot findings with silenced states.
            by_id = {f.id: f for f in updated if f.id is not None}
            for i, f in enumerate(snapshot.findings):
                if f.id in by_id:
                    snapshot.findings[i] = by_id[f.id]

    return snapshot


__all__ = [
    "core_finding_to_snapshot_finding",
    "core_findings_to_snapshot_findings",
    "create_snapshot_from_core_findings",
]
