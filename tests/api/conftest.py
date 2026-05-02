"""
Shared fixtures for web route tests.
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from unittest.mock import MagicMock

from api.app import app
from api.routes import analysis_engine
from orchestrator.runtime.models import Finding, SessionState, LearningData


@pytest.fixture
def client():
    """FastAPI test client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def reset_session():
    """Reset the shared analysis engine between tests."""
    analysis_engine.state = None
    analysis_engine.results = None
    analysis_engine.current_index = 0
    analysis_engine.analysis_progress = None
    analysis_engine.read_only_view = False
    analysis_engine.loaded_session_status = None
    yield
    analysis_engine.state = None
    analysis_engine.results = None
    analysis_engine.current_index = 0
    analysis_engine.analysis_progress = None
    analysis_engine.read_only_view = False
    analysis_engine.loaded_session_status = None


@pytest.fixture
def active_session(reset_session):
    """Set up a mock active session with findings."""
    mock_client = MagicMock()
    learning = LearningData()

    findings = [
        Finding(
            number=1, severity="critical", lens="prose",
            location="Paragraph 1", evidence="Test evidence 1",
            impact="Test impact 1", options=["Fix it", "Leave it"],
            flagged_by=["prose"]
        ),
        Finding(
            number=2, severity="major", lens="structure",
            location="Paragraph 5", evidence="Test evidence 2",
            impact="Test impact 2", options=["Restructure"],
            flagged_by=["structure"]
        ),
        Finding(
            number=3, severity="minor", lens="clarity",
            location="Paragraph 10", evidence="Test evidence 3",
            impact="Test impact 3", options=["Clarify"],
            flagged_by=["clarity"],
            ambiguity_type="ambiguous_possibly_intentional"
        ),
        Finding(
            number=4, severity="major", lens="dialogue",
            location="Paragraph 12", evidence="Dialogue voices blend",
            impact="Weakens character distinction", options=["Differentiate diction"],
            flagged_by=["dialogue"]
        ),
    ]

    analysis_engine.state = SessionState(
        client=mock_client,
        scene_content="Test scene content",
        scene_path="/test/scene.txt",
        project_path=Path("/test/project"),
        indexes={},
        scene_paths=["/test/scene.txt", "/test/scene-2.txt"],
        learning=learning,
        findings=findings,
    )
    analysis_engine.current_index = 0
