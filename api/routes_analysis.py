"""
Analysis and audit routes.

Interactive-session routes (resume, view-session, check-session, save-learning,
session-summary) were removed in session→snapshot unification (Phase 3, Task 5).
They are preserved in archive/interactive-session/routes_session.py.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from orchestrator.services import (
    audit_scene,
    audit_indexes_deterministic,
    audit_indexes_semantic,
    format_audit_report,
)
from orchestrator.services.analysis_service import resolve_model
from orchestrator.runtime.model_slots import resolve_models_for_mode
from orchestrator.user_config import get_model_slots
from orchestrator.persistence.database import get_connection
from orchestrator.services.project_knowledge_service import ensure_project_knowledge_fresh
from core.log_utils import op_start, op_complete
from .route_helpers import (
    MODE_COST_HINTS,
    analysis_engine,
    _build_tier_cost_summary,
    _ensure_finding_origins_in_response,
    _ensure_repo_preflight_ready,
    _normalise_model_name,
    _normalise_optional_model_name,
    _resolve_analysis_and_discussion_keys,
    _resolve_provider_api_key,
)
from .schemas import (
    AnalyzeRequest,
    IndexAuditRequest,
    RerunAnalyzeRequest,
    SceneAuditRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/analyze")
async def start_analysis(req: AnalyzeRequest):
    """Start a new multi-lens analysis."""
    _ensure_repo_preflight_ready()
    project = Path(req.project_path)
    if project.exists():
        knowledge_refresh = ensure_project_knowledge_fresh(project)
    else:
        knowledge_refresh = {
            "refreshed": False,
            "stale_scenes": [],
            "stale_indexes": [],
            "reason": "project_missing",
        }

    mode = (req.mode or "deep").strip().lower()

    selected_scene_paths = req.scene_paths or ([req.scene_path] if req.scene_path else [])
    if not selected_scene_paths:
        raise HTTPException(status_code=400, detail="scene_path or scene_paths is required")

    if req.model is not None or req.discussion_model is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Deprecated fields are not supported for /api/analyze: model, discussion_model. "
                "Use mode (quick/deep or a model name such as opus, sonnet, haiku)."
            ),
        )

    try:
        resolved = resolve_models_for_mode(mode, get_model_slots())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    model = _normalise_model_name(resolved["analysis_model"])
    discussion_model = _normalise_optional_model_name(resolved["discussion_model"])

    analysis_key, discussion_key = _resolve_analysis_and_discussion_keys(
        model,
        discussion_model,
        req.api_key,
        req.discussion_api_key,
    )

    depth_mode = resolved["mode"]
    try:
        result = await analysis_engine.start_analysis(
            selected_scene_paths[0],
            req.project_path,
            analysis_key,
            model=model,
            discussion_model=discussion_model,
            discussion_api_key=discussion_key,
            scene_paths=selected_scene_paths,
            depth_mode=depth_mode,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    result["mode_cost_hint"] = MODE_COST_HINTS.get(mode, MODE_COST_HINTS["deep"])
    result["tier_cost_summary"] = _build_tier_cost_summary(
        mode=mode,
        checker_model=model,
        frontier_model=discussion_model,
    )
    result["knowledge_refresh"] = knowledge_refresh

    return _ensure_finding_origins_in_response(result)


@router.post("/analyze/rerun")
async def rerun_analysis(req: RerunAnalyzeRequest):
    """Re-run analysis for the active session's scene set with current settings."""
    _ensure_repo_preflight_ready()

    if not analysis_engine.state:
        raise HTTPException(status_code=404, detail="No active session")

    model = _normalise_model_name(analysis_engine.state.model)
    discussion_model = _normalise_optional_model_name(analysis_engine.state.discussion_model)

    analysis_key, discussion_key = _resolve_analysis_and_discussion_keys(
        model,
        discussion_model,
        req.api_key,
        req.discussion_api_key,
    )

    scene_paths = analysis_engine.state.scene_paths or [analysis_engine.state.scene_path]
    depth_mode = getattr(analysis_engine.state, "depth_mode", "deep") or "deep"
    try:
        result = await analysis_engine.start_analysis(
            scene_paths[0],
            req.project_path,
            analysis_key,
            model=model,
            discussion_model=discussion_model,
            discussion_api_key=discussion_key,
            scene_paths=scene_paths,
            depth_mode=depth_mode,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return result


@router.get("/analyze/progress")
async def analysis_progress(request: Request):
    """SSE endpoint that streams analysis progress events."""
    progress = analysis_engine.analysis_progress

    if progress is None:
        raise HTTPException(status_code=404, detail="No analysis in progress")

    async def event_stream():
        # First, send any already-emitted events
        sent = 0
        for event in progress.events:
            yield f"data: {json.dumps(event)}\n\n"
            sent += 1

        # Drain the queue of events already covered by the replay above.
        # Without this, a late-connecting client receives each pre-connection
        # event twice: once from the replay and once from the live queue.
        progress.drain_replayed(sent)

        # Then stream new events as they arrive
        while not progress.complete or sent < len(progress.events):
            try:
                event = await asyncio.wait_for(progress.get_event(), timeout=1.0)
                yield f"data: {json.dumps(event)}\n\n"
                sent += 1
            except asyncio.TimeoutError:
                # Send keepalive
                if progress.complete:
                    break
                yield f": keepalive\n\n"

            # Check if client disconnected
            if await request.is_disconnected():
                break

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/audit")
async def audit_indexes(req: IndexAuditRequest):
    """Deprecated: run deterministic/deep index audit and return findings."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    from orchestrator.facade import PlatformFacade
    from orchestrator.services.analysis_service import OPTIONAL_FILES

    indexes = PlatformFacade.load_legacy_indexes_from_project(
        project,
        optional_filenames=tuple(OPTIONAL_FILES),
    )
    report = audit_indexes_deterministic(indexes)

    deep_error: Optional[str] = None
    resolved_model = _normalise_model_name(req.model)

    if req.deep:
        model_cfg = resolve_model(resolved_model)
        provider = model_cfg["provider"]
        try:
            op_start("deep_index_audit", project.name)
            api_key = _resolve_provider_api_key(provider, req.api_key, "api_key")
            from orchestrator.runtime.llm import create_client as _create_llm_client

            client = _create_llm_client(provider, api_key)
            report.semantic = await audit_indexes_semantic(
                indexes,
                client,
                model=model_cfg["id"],
                max_tokens=model_cfg["max_tokens"],
            )
            op_complete("deep_index_audit", project.name, status="ok", findings=len(report.semantic))
        except Exception as e:
            op_complete("deep_index_audit", project.name, status="failed")
            logger.warning("Deep index audit failed: %s", e)
            deep_error = str(e)

    return {
        "deterministic": [f.__dict__ for f in report.deterministic],
        "semantic": [f.__dict__ for f in report.semantic],
        "placeholder_census": report.placeholder_census,
        "formatted_report": format_audit_report(report),
        "deep": req.deep,
        "model": resolved_model,
        "deep_error": deep_error,
        "deprecated": True,
        "replacement": "/api/knowledge/refresh",
    }


@router.post("/scenes/audit")
async def audit_scene_route(req: SceneAuditRequest):
    """Deprecated: run deterministic/deep scene audit and return findings."""
    project = Path(req.project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    scene_path = Path(req.scene_path)
    if not scene_path.exists():
        raise HTTPException(status_code=404, detail="Scene file not found")

    try:
        scene_content = scene_path.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot read scene file: {e}") from e

    from orchestrator.facade import PlatformFacade
    from orchestrator.services.analysis_service import OPTIONAL_FILES

    indexes = PlatformFacade.load_legacy_indexes_from_project(
        project,
        optional_filenames=tuple(OPTIONAL_FILES),
    )

    deep_error: Optional[str] = None
    resolved_model = _normalise_model_name(req.model)
    model_cfg = resolve_model(resolved_model)
    model_id = model_cfg["id"]
    max_tokens = model_cfg["max_tokens"]
    client = None

    if req.deep:
        provider = model_cfg["provider"]
        try:
            op_start("deep_scene_audit", scene_path.name)
            api_key = _resolve_provider_api_key(provider, req.api_key, "api_key")
            from orchestrator.runtime.llm import create_client as _create_llm_client

            client = _create_llm_client(provider, api_key)
        except Exception as e:
            op_complete("deep_scene_audit", scene_path.name, status="setup_failed")
            logger.warning("Deep scene audit setup failed: %s", e)
            deep_error = str(e)

    result = await audit_scene(
        scene_content,
        indexes,
        deep=req.deep,
        client=client,
        model=model_id,
        max_tokens=max_tokens,
    )
    if req.deep and not deep_error:
        if result.get("deep_error"):
            op_complete("deep_scene_audit", scene_path.name, status="failed")
        else:
            op_complete("deep_scene_audit", scene_path.name, status="ok", findings=len(result.get("semantic", [])))

    if deep_error and not result.get("deep_error"):
        result["deep_error"] = deep_error

    return {
        "deterministic": [f.__dict__ for f in result["deterministic"]],
        "semantic": [f.__dict__ for f in result["semantic"]],
        "deep": req.deep,
        "model": resolved_model,
        "deep_error": result.get("deep_error"),
        "deprecated": True,
        "replacement": "/api/knowledge/refresh",
    }


@router.delete("/analysis/snapshots/by-scene")
async def delete_analysis_snapshot_for_scene(
    project_path: str = Query(..., description="Path to the project directory"),
    scene_path: str = Query(..., description="Path to the scene file whose analysis should be deleted"),
):
    """Delete the analysis snapshot (and its findings) for a specific scene."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    snapshot_ids: list[int] = []
    conn = get_connection(project)
    try:
        rows = conn.execute(
            "SELECT id FROM analysis_snapshot WHERE scene_paths LIKE ?",
            (f"%{scene_path}%",),
        ).fetchall()
        snapshot_ids = [r[0] for r in rows]
        if snapshot_ids:
            placeholders = ",".join("?" * len(snapshot_ids))
            conn.execute(
                f"DELETE FROM snapshot_finding WHERE snapshot_id IN ({placeholders})",
                snapshot_ids,
            )
            conn.execute(
                f"DELETE FROM analysis_snapshot WHERE id IN ({placeholders})",
                snapshot_ids,
            )
            conn.commit()
    finally:
        conn.close()

    return {"deleted": True, "count": len(snapshot_ids)}


@router.delete("/analysis/snapshots")
async def delete_all_analysis_snapshots(
    project_path: str = Query(..., description="Path to the project directory"),
):
    """Delete all analysis_snapshot rows for a project, resetting scene analysis state."""
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")

    conn = get_connection(project)
    try:
        conn.execute("DELETE FROM analysis_snapshot")
        conn.commit()
    finally:
        conn.close()

    return {"deleted": True}


