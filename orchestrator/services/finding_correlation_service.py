"""Finding correlation service — match findings across analysis runs (Task C5).

When a new analysis runs on a scene, this service:
1. Correlates new findings with the previous snapshot using ``correlation_key``.
2. Carries over the silenced state to correlated findings so silence rules persist.
3. Marks previous findings that didn't reappear as ``resolved``.

Per feasibility §4.3:
  "Findings that match a previous finding ... are *correlated* — the author sees
   continuity, not a fresh list each time."
"""

from __future__ import annotations

import sqlite3

from core.domain import SnapshotFinding
from orchestrator.persistence.snapshot_store import SnapshotStore


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def identify_resolved_findings(
    previous_findings: list[SnapshotFinding],
    new_findings: list[SnapshotFinding],
) -> list[SnapshotFinding]:
    """Return previous findings that no longer appear in *new_findings*.

    A finding is considered resolved when its ``correlation_key`` is absent
    from the new set.  Only ``active`` and ``silenced`` previous findings
    are checked — already-resolved ones are skipped.

    This is a **pure function** — no DB access.
    """
    new_keys = {nf.correlation_key for nf in new_findings if nf.correlation_key}
    resolved = []
    for pf in previous_findings:
        if pf.state == "resolved":
            continue
        if pf.correlation_key not in new_keys:
            resolved.append(pf)
    return resolved


def persist_resolved_findings(
    conn: sqlite3.Connection,
    resolved: list[SnapshotFinding],
) -> None:
    """Write ``state="resolved"`` to the DB for each finding in *resolved*."""
    for finding in resolved:
        if finding.id is not None:
            SnapshotStore.update_finding_state(conn, finding.id, "resolved")


__all__ = [
    "identify_resolved_findings",
    "persist_resolved_findings",
]
