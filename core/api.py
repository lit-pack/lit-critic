"""FastAPI app for the stateless Core service."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

import core.service as core_service
from core import __version__ as CORE_VERSION
from contracts.v1.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ReEvaluateFindingRequest,
    ReEvaluateFindingResponse,
)
from orchestrator.runtime.config import resolve_api_key, resolve_model
from orchestrator.runtime.llm.factory import create_client

app = FastAPI(
    title="lit-critic-core",
    description="Stateless core API (text/context in, structured results out)",
    version=CORE_VERSION,
)


def _resolve_client_and_model_id(model_name: str, api_keys: dict[str, str]):
    """Resolve provider/model id and construct a provider client."""
    try:
        model_cfg = resolve_model(model_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    provider = model_cfg["provider"]
    explicit_key = api_keys.get(provider)
    try:
        api_key = resolve_api_key(provider, explicit_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        client = create_client(provider, api_key)
    except (ValueError, ImportError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return client, model_cfg["id"]


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness/readiness probe endpoint."""
    return {"status": "ok"}


@app.post("/v1/analyze", response_model=AnalyzeResponse)
async def analyze_v1(request: AnalyzeRequest) -> AnalyzeResponse:
    """Analyze scene text using the v1 stateless contract."""
    client, resolved_model_id = _resolve_client_and_model_id(
        request.model_settings.analysis_model,
        request.model_settings.api_keys,
    )
    request = request.model_copy(
        update={
            "model_settings": request.model_settings.model_copy(
                update={"analysis_model": resolved_model_id}
            )
        }
    )
    return await core_service.analyze(request, client=client)


@app.post("/v1/re-evaluate-finding", response_model=ReEvaluateFindingResponse)
async def re_evaluate_v1(request: ReEvaluateFindingRequest) -> ReEvaluateFindingResponse:
    """Re-evaluate a stale finding against updated scene text."""
    client, resolved_model_id = _resolve_client_and_model_id(
        request.model_settings.analysis_model,
        request.model_settings.api_keys,
    )
    request = request.model_copy(
        update={
            "model_settings": request.model_settings.model_copy(
                update={"analysis_model": resolved_model_id}
            )
        }
    )
    return await core_service.re_evaluate(request, client=client)
