"""
Silence rule REST API endpoints.

POST   /api/silence-rules              Create a silence rule
GET    /api/silence-rules              List silence rules
PATCH  /api/silence-rules/{rule_id}    Suspend or unsuspend a rule
DELETE /api/silence-rules/{rule_id}    Delete a rule
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from orchestrator.persistence.database import get_connection
from orchestrator.services.silence_rule_service import (
    create_rule,
    delete_rule,
    list_applicable_rules,
    list_rules,
    suspend_rule,
)
from core.domain import SilenceRule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/silence-rules", tags=["silence-rules"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SilenceRuleCreateRequest(BaseModel):
    """Body for POST /api/silence-rules."""
    rule_type: str           # instance | pattern | category
    scope: str = "scene"     # scene | project
    scene_path: str = ""
    finding_id: Optional[int] = None
    lens: str = ""
    severity: str = ""
    text_pattern: str = ""
    note: str = ""
    created_at: str = ""


class SilenceRulePatchRequest(BaseModel):
    """Body for PATCH /api/silence-rules/{rule_id}."""
    suspended: bool
    suspended_at: str = ""


class SilenceRuleResponse(BaseModel):
    id: int
    rule_type: str
    scope: str
    scene_path: str
    finding_id: Optional[int]
    lens: str
    severity: str
    text_pattern: str
    note: str
    suspended: bool
    created_at: str
    suspended_at: str


def _to_response(rule: SilenceRule) -> SilenceRuleResponse:
    return SilenceRuleResponse(
        id=rule.id,
        rule_type=rule.rule_type,
        scope=rule.scope,
        scene_path=rule.scene_path,
        finding_id=rule.finding_id,
        lens=rule.lens,
        severity=rule.severity,
        text_pattern=rule.text_pattern,
        note=rule.note,
        suspended=rule.suspended,
        created_at=rule.created_at,
        suspended_at=rule.suspended_at,
    )


def _check_project(project_path: str) -> Path:
    project = Path(project_path)
    if not project.exists():
        raise HTTPException(status_code=404, detail="Project directory not found")
    return project


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=SilenceRuleResponse, status_code=201)
async def create_silence_rule(
    body: SilenceRuleCreateRequest,
    project_path: str = Query(..., description="Absolute path to the project directory"),
) -> SilenceRuleResponse:
    """Create a new silence rule for this project."""
    project = _check_project(project_path)
    rule = SilenceRule(
        rule_type=body.rule_type,
        scope=body.scope,
        scene_path=body.scene_path,
        finding_id=body.finding_id,
        lens=body.lens,
        severity=body.severity,
        text_pattern=body.text_pattern,
        note=body.note,
        created_at=body.created_at,
    )
    conn = get_connection(project)
    try:
        create_rule(conn, rule, project_path=project)
    finally:
        conn.close()
    return _to_response(rule)


@router.get("", response_model=list[SilenceRuleResponse])
async def list_silence_rules(
    project_path: str = Query(..., description="Absolute path to the project directory"),
    scene_path: Optional[str] = Query(None, description="If given, return only rules applicable to this scene"),
    include_suspended: bool = Query(True, description="Include suspended rules"),
) -> list[SilenceRuleResponse]:
    """List silence rules for this project.

    If ``scene_path`` is provided, returns only rules applicable to that scene
    (scene-scoped rules for that scene + all project-wide rules, active only).
    Otherwise, returns all rules.
    """
    project = _check_project(project_path)
    conn = get_connection(project)
    try:
        if scene_path is not None:
            rules = list_applicable_rules(conn, scene_path, project_path=project)
        else:
            rules = list_rules(
                conn, project_path=project, include_suspended=include_suspended
            )
    finally:
        conn.close()
    return [_to_response(r) for r in rules]


@router.patch("/{rule_id}", response_model=SilenceRuleResponse)
async def patch_silence_rule(
    rule_id: int,
    body: SilenceRulePatchRequest,
    project_path: str = Query(..., description="Absolute path to the project directory"),
) -> SilenceRuleResponse:
    """Suspend or unsuspend a silence rule."""
    project = _check_project(project_path)
    conn = get_connection(project)
    try:
        updated = suspend_rule(
            conn,
            rule_id,
            suspended=body.suspended,
            suspended_at=body.suspended_at,
            project_path=project,
        )
    finally:
        conn.close()
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Silence rule {rule_id} not found")
    return _to_response(updated)


@router.delete("/{rule_id}", status_code=204)
async def delete_silence_rule(
    rule_id: int,
    project_path: str = Query(..., description="Absolute path to the project directory"),
) -> None:
    """Permanently delete a silence rule."""
    project = _check_project(project_path)
    conn = get_connection(project)
    try:
        existed = delete_rule(conn, rule_id)
    finally:
        conn.close()
    if not existed:
        raise HTTPException(status_code=404, detail=f"Silence rule {rule_id} not found")
