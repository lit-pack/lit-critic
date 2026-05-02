"""Platform-owned snapshot workflow service.

Replaces the legacy interactive-session service after the session→snapshot
unification (specs/session-to-snapshot-unification-plan.md, Tasks 10–11).
All analysis data is sourced from `analysis_snapshot` / `snapshot_finding`.
The `session` and `finding` tables were dropped in migration v22.
"""

import hashlib
import json
from pathlib import Path
from typing import Optional

from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.knowledge_state_store import KnowledgeStateStore
from orchestrator.persistence.database import get_connection, get_passive_connection
from orchestrator.persistence.snapshot_store import SnapshotStore
from orchestrator.persistence.path_utils import to_absolute

from core.domain import AnalysisSnapshot
from orchestrator.runtime.config import CONTEXT_FILES


# ---------------------------------------------------------------------------
# Utility helpers (kept for callers in session_manager.py / analysis pipeline)
# ---------------------------------------------------------------------------


def compute_scene_hash(scene_content: str) -> str:
    """Compute a hash of the scene content for change detection."""
    return hashlib.sha256(scene_content.encode("utf-8")).hexdigest()[:16]


def compute_index_context_hash(indexes: dict[str, str]) -> str:
    """Compute a stable hash for context-bearing index inputs."""
    normalized_payload = {
        name: indexes.get(name, "")
        for name in CONTEXT_FILES
    }
    payload = json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Stubs — interactive sessions no longer exist
# ---------------------------------------------------------------------------


def check_active_session(project_path: Path, passive: bool = False) -> dict:
    """Always returns {'exists': False} — interactive sessions removed in v22."""
    return {"exists": False}


def complete_active_session(project_path: Path) -> bool:
    """No-op — interactive sessions removed in v22. Always returns False."""
    return False


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _get_read_connection(project_path: Path, *, passive: bool):
    """Return the appropriate read connection."""
    if passive:
        return get_passive_connection(project_path)
    return get_connection(project_path)


# ---------------------------------------------------------------------------
# Snapshot list / detail
# ---------------------------------------------------------------------------


def list_sessions(project_path: Path, passive: bool = False) -> list[dict]:
    """List all analysis snapshots for the project, newest first.

    Returns snapshot records in the same shape the Sessions tree and
    routes_management.py expect (using 'auto' as status).
    """
    conn = _get_read_connection(project_path, passive=passive)
    if conn is None:
        return []

    try:
        snapshots = SnapshotStore.list_recent(conn, limit=50)
        result: list[dict] = []
        for snap in snapshots:
            count_row = conn.execute(
                "SELECT COUNT(*) FROM snapshot_finding WHERE snapshot_id = ?",
                (snap.id,),
            ).fetchone()
            total_findings = count_row[0] if count_row else 0

            scene_paths: list[str] = list(snap.scene_paths or [])
            scene_paths = [
                str(to_absolute(project_path, p) or p)
                for p in scene_paths
            ]
            scene_path = scene_paths[0] if scene_paths else ""

            result.append({
                "id": snap.id,
                "status": "auto",
                "depth_mode": snap.depth_mode or "quick",
                "scene_path": scene_path,
                "scene_paths": scene_paths,
                "model": snap.quick_model or snap.frontier_model or "",
                "created_at": snap.created_at,
                "completed_at": snap.created_at,
                "total_findings": total_findings,
                "accepted_count": 0,
                "rejected_count": 0,
                "withdrawn_count": 0,
                "index_context_stale": False,
                "index_changed_files": [],
                "rerun_recommended": False,
            })
        return result
    finally:
        conn.close()


def get_session_detail(
    project_path: Path,
    session_id: int,
    passive: bool = False,
) -> Optional[dict]:
    """Get a snapshot and its findings by id."""
    conn = _get_read_connection(project_path, passive=passive)
    if conn is None:
        return None

    try:
        snap = SnapshotStore.get(conn, session_id)
        if snap is None:
            return None

        scene_paths: list[str] = list(snap.scene_paths or [])
        scene_paths = [
            str(to_absolute(project_path, p) or p)
            for p in scene_paths
        ]
        scene_path = scene_paths[0] if scene_paths else ""

        findings_rows = conn.execute(
            """SELECT id, number, lens, severity, location, line_start, line_end,
                      scene_path, evidence, impact, options, flagged_by,
                      ambiguity_type
               FROM snapshot_finding WHERE snapshot_id = ?
               ORDER BY number""",
            (session_id,),
        ).fetchall()

        findings: list[dict] = []
        for row in findings_rows:
            f = dict(row)
            # snapshot_finding has no origin column — all loop-produced findings
            # are LLM-generated; default to "llm" for extension compatibility.
            f.setdefault("origin", "llm")
            for key in ("options", "flagged_by"):
                if isinstance(f.get(key), str):
                    try:
                        f[key] = json.loads(f[key])
                    except (ValueError, TypeError):
                        f[key] = []
            if f.get("scene_path"):
                abs_p = to_absolute(project_path, f["scene_path"])
                if abs_p:
                    f["scene_path"] = str(abs_p)
            findings.append(f)

        return {
            "id": snap.id,
            "status": "auto",
            "depth_mode": snap.depth_mode or "quick",
            "scene_path": scene_path,
            "scene_paths": scene_paths,
            "model": snap.quick_model or snap.frontier_model or "",
            "created_at": snap.created_at,
            "total_findings": len(findings),
            "findings": findings,
            "index_context_stale": False,
            "index_changed_files": [],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Current findings (latest per scene)
# ---------------------------------------------------------------------------


def get_current_findings(project_path: Path, passive: bool = False) -> dict:
    """Return the latest findings per scene in a single response.

    Groups findings by scene path, using the most recent snapshot that
    contains each scene.  This replaces the N+1 hydration pattern of
    ``list_sessions`` + ``get_session_detail`` × N.

    Returns::

        {
            "scenes": {
                "<absolute scene path>": {
                    "snapshot_id": int,
                    "depth_mode": str,
                    "model": str,
                    "created_at": str,
                    "findings": [<finding dict>, ...]
                },
                ...
            }
        }
    """
    conn = _get_read_connection(project_path, passive=passive)
    if conn is None:
        return {"scenes": {}}

    try:
        snapshots = SnapshotStore.list_recent(conn, limit=50)

        # Map each scene path → its latest snapshot id.
        scene_to_snapshot: dict[str, AnalysisSnapshot] = {}
        for snap in snapshots:
            for rel_path in (snap.scene_paths or []):
                abs_path = str(to_absolute(project_path, rel_path) or rel_path)
                if abs_path not in scene_to_snapshot:
                    scene_to_snapshot[abs_path] = snap

        # Collect unique snapshot ids we need findings for.
        needed_ids = {snap.id for snap in scene_to_snapshot.values()}

        # Bulk-load findings for those snapshots.
        findings_by_snapshot: dict[int, list[dict]] = {sid: [] for sid in needed_ids}
        if needed_ids:
            placeholders = ",".join("?" for _ in needed_ids)
            rows = conn.execute(
                f"""SELECT id, number, snapshot_id, lens, severity, location,
                           line_start, line_end, scene_path, evidence,
                           impact, options, flagged_by, ambiguity_type,
                           state, correlation_key
                    FROM snapshot_finding
                    WHERE snapshot_id IN ({placeholders})
                    ORDER BY number""",
                list(needed_ids),
            ).fetchall()
            for row in rows:
                f = dict(row)
                # Normalise DB column name "state" → API field name "status"
                f["status"] = f.pop("state", "active") or "active"
                f.setdefault("origin", "llm")
                for key in ("options", "flagged_by"):
                    if isinstance(f.get(key), str):
                        try:
                            f[key] = json.loads(f[key])
                        except (ValueError, TypeError):
                            f[key] = []
                if f.get("scene_path"):
                    abs_p = to_absolute(project_path, f["scene_path"])
                    if abs_p:
                        f["scene_path"] = str(abs_p)
                findings_by_snapshot[f["snapshot_id"]].append(f)

        # Build scene-grouped response.
        scenes: dict[str, dict] = {}
        for abs_scene, snap in scene_to_snapshot.items():
            scene_findings = [
                f for f in findings_by_snapshot.get(snap.id, [])
                if f.get("scene_path") == abs_scene
            ]
            scenes[abs_scene] = {
                "snapshot_id": snap.id,
                "depth_mode": snap.depth_mode or "quick",
                "model": snap.quick_model or snap.frontier_model or "",
                "created_at": snap.created_at,
                "findings": scene_findings,
            }

        return {"scenes": scenes}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Delete operations
# ---------------------------------------------------------------------------


def delete_session_by_id(project_path: Path, session_id: int) -> bool:
    """Delete a specific snapshot by id. Returns True if deleted."""
    conn = get_connection(project_path)
    try:
        return SnapshotStore.delete_by_id(conn, session_id)
    finally:
        conn.close()


def delete_all_sessions(project_path: Path) -> int:
    """Delete all snapshots. Returns the number deleted."""
    conn = get_connection(project_path)
    try:
        return SnapshotStore.delete_all(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Knowledge reset
# ---------------------------------------------------------------------------


def reset_all_knowledge(project_path: Path) -> None:
    """Delete all extracted knowledge, overrides, review flags and staleness cache."""
    conn = get_connection(project_path)
    try:
        ExtractionStore.reset(conn)
        KnowledgeStateStore.clear_review_flags(conn)
        KnowledgeStateStore.clear_staleness_cache(conn)
        conn.execute("DELETE FROM knowledge_overrides")
        conn.commit()
    finally:
        conn.close()
