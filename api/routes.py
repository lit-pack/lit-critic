"""
REST API routes aggregator for the lit-critic API server.

This module combines all domain-specific routers into a single router
that is registered with the FastAPI application in app.py.
"""

from fastapi import APIRouter

from .routes_config import router as config_router
from .routes_analysis import router as analysis_router
from .routes_management import router as management_router
from .routes_silence import router as silence_router
from .routes_explain import router as explain_router

# Re-exported for test and analysis-engine access
from .route_helpers import analysis_engine  # noqa: F401

router = APIRouter(prefix="/api")
router.include_router(config_router)
router.include_router(analysis_router)
router.include_router(management_router)
router.include_router(silence_router)
router.include_router(explain_router)
