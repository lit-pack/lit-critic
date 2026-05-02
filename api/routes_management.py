"""
Management routes: sessions, scenes, indexes, knowledge, analytics, learning.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from orchestrator.user_config import (
    get_scene_discovery_settings,
    set_knowledge_review_pass_setting,
)
from orchestrator.persistence import ExtractionStore, LearningStore, get_connection
from orchestrator.persistence.database import get_passive_connection
from orchestrator.services import (
    get_current_findings,
    load_learning,
    export_learning_markdown,
)
from orchestrator.services.session_service import (
    reset_all_knowledge,
)
from orchestrator.services.scene_projection_service import (
    compute_file_hash,
    discover_scene_relative_paths,
    list_scene_projections,
)
from orchestrator.services.index_projection_service import (
    get_stale_indexes,
    list_index_projections,
)
from orchestrator.services.project_knowledge_service import (
    _knowledge_affected_by_scene,
    detect_orphaned_scene_data,
    get_project_knowledge_status,
    refresh_project_knowledge,
)
from orchestrator.services.scene_status_service import (
    SceneStatus,
    list_analyzable_scenes,
    list_scene_statuses,
)
from orchestrator.services.index_status_service import (
    IndexStatus,
    list_index_statuses,
)
from orchestrator.services.rename_service import purge_orphaned_scene_refs, rename_scene
from orchestrator.services.knowledge_review_service import (
    delete_entity as delete_knowledge_entity,
    delete_override as delete_knowledge_override,
    dismiss_review_flag,
    export_knowledge_markdown,
    get_knowledge_review,
    submit_override,
)
from .route_helpers import _debug_scenes_trace
from .schemas import (
    KnowledgeEntityDeleteRequest,
    KnowledgeExportRequest,
    KnowledgeLockRequest,
    KnowledgeOverrideDeleteRequest,
    KnowledgeOverrideRequest,
    KnowledgeReviewPassRequest,
    LearningEntryDeleteRequest,
    ProjectPathRequest,
    SceneLockRequest,
    SceneRenameRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/findings/current")
async def get_current_findings_route(
    project_path: str = Query(..., description="Path to the project directory"),
):
    """Return the latest findings per scene in a single call.

    Replaces the N+1 hydration pattern of listSessions + getSessionDetail × N.
    """
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    return get_current_findings(project, passive=True)


@router.get("/scenes")
async def list_scenes_route(project_path: str = Query(..., description="Path to the project directory")):
    """List projected scenes for a project."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    scene_folder, scene_extensions = get_scene_discovery_settings()
    scenes = list_scene_projections(project)

    # Append un-projected discoverable files so the UI can show them as stale
    projected_paths = {s.get("scene_path") for s in scenes}
    for disk_path in discover_scene_relative_paths(project):
        if disk_path not in projected_paths:
            scenes.append({
                "scene_path": disk_path,
                "stale": True,
            })

    _debug_scenes_trace(
        "GET /api/scenes",
        project_path=str(project),
        effective_scene_folder=scene_folder,
        effective_scene_extensions=list(scene_extensions),
        scene_count=len(scenes),
        first_scene_paths=[row.get("scene_path") for row in scenes[:5]],
    )
    return {"scenes": scenes}


@router.get("/scenes/analyzable")
async def get_analyzable_scenes_route(
    project_path: str = Query(..., description="Path to the project directory"),
):
    """Return scenes that are ready to be analyzed.

    A scene is analyzable when its status is ``extraction_due`` or ``extracted``.
    Returns an empty list when no DB exists yet.
    """
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_passive_connection(project)
    if conn is None:
        return {"analyzable_scenes": []}
    try:
        scenes = list_analyzable_scenes(project, conn)
    finally:
        conn.close()

    return {"analyzable_scenes": scenes}


@router.post("/scenes/refresh")
async def refresh_scenes_route(req: ProjectPathRequest):
    """Deprecated alias for knowledge refresh."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    refreshed = refresh_project_knowledge(project)
    return {
        "deprecated": True,
        "replacement": "/api/knowledge/refresh",
        **refreshed,
    }


@router.post("/scenes/lock")
async def lock_scene_route(req: SceneLockRequest):
    """Lock a scene to skip automatic extraction during refresh."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        ExtractionStore.lock_scene(conn, req.scene_filename)
    finally:
        conn.close()

    return {
        "locked": True,
        "scene_filename": req.scene_filename,
    }


@router.post("/scenes/unlock")
async def unlock_scene_route(req: SceneLockRequest):
    """Unlock a scene so automatic extraction can run again."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        ExtractionStore.unlock_scene(conn, req.scene_filename)
    finally:
        conn.close()

    return {
        "unlocked": True,
        "scene_filename": req.scene_filename,
    }


@router.post("/scenes/rename")
async def rename_scene_route(req: SceneRenameRequest):
    """Rename a scene and propagate Prev/Next and DB references."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        try:
            rename_result = rename_scene(
                project_path=project,
                old_filename=req.old_filename,
                new_filename=req.new_filename,
                conn=conn,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()

    return {
        "renamed": True,
        **rename_result,
    }


@router.post("/scenes/purge-orphans")
async def purge_orphaned_scene_refs_route(req: ProjectPathRequest):
    """Delete DB rows whose scene path no longer matches any discoverable scene file."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        result = purge_orphaned_scene_refs(project, conn)
    finally:
        conn.close()

    return result


@router.get("/scenes/{scene_path:path}/status")
async def get_scene_status_route(
    scene_path: str,
    project_path: str = Query(..., description="Path to the project directory"),
):
    """Return stale/fresh status for one scene projection."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    normalized_scene_path = Path(scene_path).as_posix()
    scene_file = project / normalized_scene_path
    if not scene_file.exists():
        raise HTTPException(status_code=404, detail="Scene file not found")

    current_hash = compute_file_hash(scene_file)
    projection = next(
        (
            row
            for row in list_scene_projections(project)
            if row.get("scene_path") == normalized_scene_path
        ),
        None,
    )
    stored_hash = projection.get("file_hash") if projection else None

    return {
        "scene_path": normalized_scene_path,
        "stale": stored_hash != current_hash,
        "projected": projection is not None,
        "file_hash": current_hash,
        "stored_hash": stored_hash,
    }


@router.get("/indexes")
async def list_indexes_route(project_path: str = Query(..., description="Path to the project directory")):
    """List projected indexes for a project."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    indexes = list_index_projections(project)
    return {
        "indexes": indexes,
        "deprecated": True,
        "replacement": "/api/knowledge/refresh",
    }


@router.post("/indexes/refresh")
async def refresh_indexes_route(req: ProjectPathRequest):
    """Deprecated alias for knowledge refresh."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    refreshed = refresh_project_knowledge(project)
    return {
        "deprecated": True,
        "replacement": "/api/knowledge/refresh",
        **refreshed,
    }


@router.get("/indexes/status")
async def get_indexes_status_route(project_path: str = Query(..., description="Path to the project directory")):
    """Return stale index projection keys for a project."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    stale_indexes = get_stale_indexes(project)
    return {
        "stale_indexes": stale_indexes,
        "stale_count": len(stale_indexes),
        "projected_count": len(list_index_projections(project)),
        "deprecated": True,
        "replacement": "/api/knowledge/refresh",
    }


@router.post("/knowledge/refresh")
async def refresh_knowledge_route(req: ProjectPathRequest):
    """Refresh scene/index projections and extracted knowledge for a project."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    refreshed = refresh_project_knowledge(project)
    _debug_scenes_trace(
        "POST /api/knowledge/refresh",
        project_path=str(project),
        scene_total=refreshed.get("scene_total"),
        scene_updated=refreshed.get("scene_updated"),
        index_total=refreshed.get("index_total"),
        index_updated=refreshed.get("index_updated"),
        extraction_scenes=refreshed.get("extraction", {}).get("scenes_processed"),
    )
    return refreshed


@router.get("/inputs/staleness")
async def get_inputs_staleness_route(
    project_path: str = Query(..., description="Path to the project directory"),
):
    """Return stale input files (references and scenes) and their dependent knowledge/sessions."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_passive_connection(project)
    if conn is None:
        result: dict = {"stale_inputs": []}
    else:
        try:
            result = _staleness_from_status(project, conn)
        finally:
            conn.close()

    try:
        orphaned = detect_orphaned_scene_data(project)
        result["orphaned_scenes"] = orphaned.get("orphaned_scenes", [])
    except Exception:  # noqa: BLE001 - orphan detection is non-fatal
        result["orphaned_scenes"] = []
    return result


def _staleness_from_status(project: Path, conn) -> dict:
    """Build staleness response using scene/index status services.

    Response schema matches the old ``compute_input_staleness`` for
    extension compatibility::

        {"stale_inputs": [{
            "path": "<absolute path>",
            "type": "reference" | "scene",
            "affected_knowledge": [...] | "all",
            "affected_sessions": [<int>, ...],
        }]}
    """
    import hashlib
    import sqlite3
    from orchestrator.persistence.session_store import SessionStore

    stale_inputs: list[dict] = []
    try:
        all_sessions = SessionStore.list_all(conn, project_path=project)
    except sqlite3.OperationalError:
        all_sessions = []

    # --- References (indexes) via index_status_service ---
    for rec in list_index_statuses(project, conn):
        if rec.status != IndexStatus.stale:
            continue
        affected_knowledge: list | str = "all" if rec.affects_knowledge else []
        stale_inputs.append({
            "path": str(project / rec.index_name),
            "type": "reference",
            "affected_knowledge": affected_knowledge,
            "affected_sessions": [s["id"] for s in all_sessions],
        })

    # --- Scenes via scene_status_service ---
    for rec in list_scene_statuses(project, conn):
        if rec.status != SceneStatus.extraction_due:
            continue
        scene_file = project / rec.scene_key
        if not scene_file.exists():
            continue

        scene_filename = Path(rec.scene_key).name
        affected_knowledge = _knowledge_affected_by_scene(conn, scene_filename)

        # Compute session-level scene hash (SHA-256, 16 chars) for
        # affected_sessions comparison — same algorithm as session creation.
        scene_content = scene_file.read_text(encoding="utf-8")
        current_scene_hash = hashlib.sha256(
            scene_content.encode("utf-8")
        ).hexdigest()[:16]

        affected_session_ids = []
        for s in all_sessions:
            scene_paths = s.get("scene_paths") or []
            if scene_filename not in {Path(p).name for p in scene_paths}:
                continue
            if s.get("scene_hash", "") != current_scene_hash:
                affected_session_ids.append(s["id"])

        stale_inputs.append({
            "path": str(scene_file),
            "type": "scene",
            "affected_knowledge": affected_knowledge,
            "affected_sessions": affected_session_ids,
        })

    return {"stale_inputs": stale_inputs}


@router.get("/knowledge/review")
async def get_knowledge_review_route(
    category: str = Query(..., description="Knowledge category to review"),
    project_path: str = Query(..., description="Path to the project directory"),
):
    """Return extracted entities and overrides for one knowledge category."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_passive_connection(project)
    if conn is None:
        # DB not yet created — return an empty review rather than creating the DB.
        return {"category": category, "entity_key_field": "name", "entities": [], "raw_entities": [], "overrides": []}
    try:
        try:
            return get_knowledge_review(conn, category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/knowledge/override")
async def submit_knowledge_override_route(req: KnowledgeOverrideRequest):
    """Save an author override for one extracted knowledge field."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        try:
            submit_override(
                conn,
                category=req.category,
                entity_key=req.entity_key,
                field_name=req.field_name,
                value=req.value,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()

    return {
        "updated": True,
        "category": req.category,
        "entity_key": req.entity_key,
        "field_name": req.field_name,
    }


@router.delete("/knowledge/override")
async def delete_knowledge_override_route(req: KnowledgeOverrideDeleteRequest):
    """Delete one previously saved knowledge override field value."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        try:
            deleted = delete_knowledge_override(
                conn,
                category=req.category,
                entity_key=req.entity_key,
                field_name=req.field_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()

    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge override not found")

    return {
        "deleted": True,
        "category": req.category,
        "entity_key": req.entity_key,
        "field_name": req.field_name,
    }


@router.delete("/knowledge/entity")
async def delete_knowledge_entity_route(req: KnowledgeEntityDeleteRequest):
    """Delete an extracted knowledge entity and all its overrides."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        try:
            deleted = delete_knowledge_entity(
                conn,
                category=req.category,
                entity_key=req.entity_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()

    from orchestrator.services.knowledge_review_service import _normalize_category as _norm
    try:
        normalized = _norm(req.category)
    except ValueError:
        normalized = req.category

    return {
        "deleted": deleted,
        "entity_key": req.entity_key,
        "category": normalized,
    }


@router.post("/knowledge/export")
async def export_knowledge_route(req: KnowledgeExportRequest):
    """Export extracted knowledge (with overrides) as markdown text."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        markdown = export_knowledge_markdown(conn)
    finally:
        conn.close()

    return {
        "markdown": markdown,
    }


@router.post("/knowledge/review-pass")
async def set_knowledge_review_pass_route(req: KnowledgeReviewPassRequest):
    """Set the knowledge reconciliation review pass trigger setting."""
    try:
        set_knowledge_review_pass_setting(req.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"knowledge_review_pass": req.value}


@router.post("/knowledge/lock")
async def lock_knowledge_entity_route(req: KnowledgeLockRequest):
    """Lock a knowledge entity to prevent LLM updates and deletion."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        ExtractionStore.lock_entity(conn, req.category, req.entity_key)
    finally:
        conn.close()

    return {
        "category": req.category,
        "entity_key": req.entity_key,
        "locked": True,
    }


@router.post("/knowledge/unlock")
async def unlock_knowledge_entity_route(req: KnowledgeLockRequest):
    """Unlock a knowledge entity so it can be updated by the LLM."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        ExtractionStore.unlock_entity(conn, req.category, req.entity_key)
    finally:
        conn.close()

    return {
        "category": req.category,
        "entity_key": req.entity_key,
        "locked": False,
    }


@router.post("/knowledge/dismiss-flag")
async def dismiss_knowledge_review_flag_route(req: KnowledgeLockRequest):
    """Dismiss a knowledge review flag for one entity (keep entity, clear flag)."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        dismiss_review_flag(conn, req.category, req.entity_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()

    return {"dismissed": True, "category": req.category, "entity_key": req.entity_key}


@router.delete("/knowledge")
async def reset_all_knowledge_route(project_path: str = Query(..., description="Path to the project directory")):
    """Delete ALL extracted knowledge, overrides, review flags and staleness cache."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    reset_all_knowledge(project)
    return {"reset": True}


@router.post("/project/refresh")
async def refresh_project_knowledge_route(req: ProjectPathRequest):
    """Refresh both scene and index projections for a project."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    scene_folder, scene_extensions = get_scene_discovery_settings()
    refreshed = refresh_project_knowledge(project)
    _debug_scenes_trace(
        "POST /api/project/refresh",
        project_path=str(project),
        effective_scene_folder=scene_folder,
        effective_scene_extensions=list(scene_extensions),
        scene_total=refreshed.get("scene_total"),
        scene_updated=refreshed.get("scene_updated"),
        index_total=refreshed.get("index_total"),
        index_updated=refreshed.get("index_updated"),
    )
    return refreshed


@router.get("/project/status")
async def get_project_status_route(project_path: str = Query(..., description="Path to the project directory")):
    """Return project-knowledge freshness summary for a project."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    return get_project_knowledge_status(project)


@router.get("/learning")
async def get_learning_route(project_path: str = Query(..., description="Path to the project directory")):
    """Get learning data for a project."""
    project = Path(project_path)

    # Log for debugging path encoding issues
    logger.info(f"GET /api/learning: project_path={project_path!r}, exists={project.exists()}")

    if not project.exists():
        logger.warning(f"Project directory not found: {project_path}")
        raise HTTPException(status_code=404, detail="Project directory not found")

    learning = load_learning(project, passive=True)

    # Convert to dict format
    return {
        "project_name": learning.project_name,
        "review_count": learning.review_count,
        "preferences": learning.preferences,
        "blind_spots": learning.blind_spots,
        "resolutions": learning.resolutions,
        "ambiguity_intentional": learning.ambiguity_intentional,
        "ambiguity_accidental": learning.ambiguity_accidental,
    }


@router.post("/learning/export")
async def export_learning_route(req: ProjectPathRequest):
    """Export LEARNING.md to the project directory."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    filepath = export_learning_markdown(project)
    return {"exported": True, "path": str(filepath)}


@router.delete("/learning")
async def reset_learning_route(project_path: str = Query(..., description="Path to the project directory")):
    """Reset all learning data for a project."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        LearningStore.reset(conn)
    finally:
        conn.close()

    return {"reset": True}


@router.delete("/learning/entries/{entry_id}")
async def delete_learning_entry_route(entry_id: int, project_path: str = Query(..., description="Path to the project directory")):
    """Delete a single learning entry."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        deleted = LearningStore.remove_entry(conn, entry_id)
    finally:
        conn.close()

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Learning entry {entry_id} not found")

    return {"deleted": True, "entry_id": entry_id}
