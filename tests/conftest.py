"""
Shared fixtures for lit-critic tests.
"""

import sys
if sys.version_info < (3, 10):
    raise RuntimeError(
        f"lit-critic requires Python 3.10+. You are running {sys.version}.\n"
        "Run: py -3.13 -m venv .venv && .venv\\Scripts\\activate && pip install -r requirements.txt"
    )

import sqlite3
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from orchestrator.runtime.models import Finding, LearningData, SessionState, LensResult, CoordinatorError
from orchestrator.runtime.llm.base import LLMResponse, LLMToolResponse
from orchestrator.runtime.db import init_db


@pytest.fixture
def mock_anthropic_client():
    """Create a mock LLMClient.

    Provides the three abstract methods as AsyncMock instances:
    - create_message       → returns LLMResponse
    - create_message_with_tool → returns LLMToolResponse
    - stream_message       → async generator (override per-test)
    """
    client = AsyncMock()
    client.create_message = AsyncMock()
    client.create_message_with_tool = AsyncMock()
    client.stream_message = AsyncMock()
    return client


@pytest.fixture
def mock_api_response():
    """Create an LLMResponse from text.

    Usage:
        client.create_message = AsyncMock(return_value=mock_api_response("text"))
    """
    def _make_response(text: str):
        return LLMResponse(text=text)
    return _make_response


@pytest.fixture
def mock_streaming_response():
    """Create an async generator factory that simulates client.stream_message().

    Yields str chunks followed by a final LLMResponse.

    Usage:
        client.stream_message = mock_streaming_response("Hello world.", ["Hello ", "world."])
    """
    def _make_stream(full_text: str, chunks: list[str] = None):
        if chunks is None:
            # Default: split into word-level chunks
            words = full_text.split(" ")
            chunks = [w + " " for w in words[:-1]] + [words[-1]]

        async def _stream(**kwargs):
            for chunk in chunks:
                yield chunk
            yield LLMResponse(text=full_text)

        return _stream

    return _make_stream


@pytest.fixture
def mock_tool_use_response():
    """Create an LLMToolResponse with tool_input.

    Usage:
        response = mock_tool_use_response({"glossary_issues": [], ...})
        client.create_message_with_tool = AsyncMock(return_value=response)
    """
    def _make_response(tool_input: dict, tool_name: str = "report_findings"):
        return LLMToolResponse(tool_input=tool_input)
    return _make_response


@pytest.fixture
def mock_text_only_response():
    """Create an LLMToolResponse with no tool input (empty dict).

    Simulates the case where the model ignored the tool/function call
    and returned plain text instead.

    Usage:
        response = mock_text_only_response("Here is the JSON: {}")
        client.create_message_with_tool = AsyncMock(return_value=response)
    """
    def _make_response(text: str):
        return LLMToolResponse(tool_input={}, raw_text=text)
    return _make_response


@pytest.fixture
def sample_coordinator_output():
    """A valid coordinator output dict (the shape returned by report_findings tool)."""
    return {
        "glossary_issues": [],
        "summary": {
            "prose": {"critical": 0, "major": 1, "minor": 0},
            "structure": {"critical": 0, "major": 0, "minor": 0},
            "coherence": {"critical": 0, "major": 0, "minor": 1},
        },
        "conflicts": [],
        "ambiguities": [],
        "findings": [
            {
                "number": 1,
                "severity": "major",
                "lens": "prose",
                "location": "Paragraph 1",
                "line_start": 3,
                "line_end": 5,
                "evidence": "Repetitive sentence starts",
                "impact": "Monotonous rhythm",
                "options": ["Vary openings"],
                "flagged_by": ["prose"],
                "ambiguity_type": None,
            },
            {
                "number": 2,
                "severity": "minor",
                "lens": "clarity",
                "location": "Paragraph 2",
                "line_start": 8,
                "line_end": 10,
                "evidence": "Unclear referent for she",
                "impact": "Reader confusion",
                "options": ["Name the character"],
                "flagged_by": ["clarity"],
                "ambiguity_type": "unclear",
            },
        ],
    }


@pytest.fixture
def sample_finding_dict():
    """Sample finding data as a dictionary."""
    return {
        "number": 1,
        "severity": "major",
        "lens": "prose",
        "location": "Paragraph 3, starting 'She moved...'",
        "evidence": "Three consecutive sentences begin with 'She'",
        "impact": "Reader notices the repetition, breaking immersion",
        "options": ["Vary sentence openings", "Combine two sentences"],
        "flagged_by": ["prose"],
        "ambiguity_type": None,
    }


@pytest.fixture
def sample_finding(sample_finding_dict):
    """Sample Finding object."""
    return Finding.from_dict(sample_finding_dict)


@pytest.fixture
def sample_learning_data():
    """Sample LearningData with some content."""
    learning = LearningData(
        project_name="Test Novel",
        review_count=3,
    )
    learning.preferences.append({"description": "[prose] Sentence fragment style — Author says: \"intentional for voice\""})
    learning.blind_spots.append({"description": "[clarity] Pronoun ambiguity in dialogue"})
    learning.ambiguity_intentional.append({"description": "Chapter 5: dream sequence imagery"})
    return learning


@pytest.fixture
def sample_indexes():
    """Sample index files content."""
    return {
        "CANON.md": "# Canon\n\nMagic system uses crystals.",
        "cast": "# Cast\n\n## Elena\nAge: 28\nRole: Protagonist",
        "glossary": "# Glossary\n\n- Lumina: magical light energy",
        "STYLE.md": "# Style\n\nPresent timeline: dry, concrete",
        "threads": "# Threads\n\n- Elena's redemption arc",
        "timeline": "# Timeline\n\nAct 1: Chapters 1-5",
    }


@pytest.fixture
def sample_scene():
    """Sample scene content for testing."""
    return """---
Scene: Test Scene
Objective: Establish character
Threads: [Elena's redemption arc]
---

Elena walked through the empty corridor. She paused at the window. She looked out at the garden. She remembered her mother's words.

The morning light cast long shadows across the stone floor. She thought about what had happened yesterday. The confrontation with George had left her shaken.

"I need to find another way," she whispered to herself.
"""


@pytest.fixture
def temp_project_dir(tmp_path, sample_indexes, sample_scene):
    """Create a temporary project directory with all required files."""
    # Create index files
    for filename, content in sample_indexes.items():
        (tmp_path / filename).write_text(content, encoding='utf-8')
    
    # Create scene file
    scene_path = tmp_path / "chapter01.md"
    scene_path.write_text(sample_scene, encoding='utf-8')
    
    return tmp_path


@pytest.fixture
def sample_lens_results():
    """Sample lens results for coordinator testing."""
    return [
        LensResult(
            lens_name="prose",
            findings=[],
            raw_output='[{"severity": "major", "location": "Paragraph 1", "evidence": "Repetitive sentence starts", "impact": "Monotonous rhythm", "options": ["Vary openings"]}]'
        ),
        LensResult(
            lens_name="structure",
            findings=[],
            raw_output='[]'
        ),
        LensResult(
            lens_name="logic",
            findings=[],
            raw_output='[]'
        ),
        LensResult(
            lens_name="clarity",
            findings=[],
            raw_output='[{"severity": "minor", "location": "Paragraph 2", "evidence": "Unclear referent for she", "impact": "Reader confusion", "options": ["Name the character"], "ambiguity_type": "unclear"}]'
        ),
        LensResult(
            lens_name="continuity",
            findings=[],
            raw_output='{"glossary_issues": [], "findings": []}'
        ),
        LensResult(
            lens_name="dialogue",
            findings=[],
            raw_output='[{"severity": "major", "location": "L12-L16", "evidence": "All characters sound identical", "impact": "Weakens voice distinction", "options": ["Differentiate diction per speaker"]}]'
        ),
    ]


@pytest.fixture
def db_conn(tmp_path):
    """Create an in-memory SQLite connection with the lit-critic schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _wal_checkpoint_cleanup(tmp_path):
    """After every test, checkpoint and truncate any WAL-mode SQLite databases
    left in tmp_path.  This releases the memory-mapped -shm handle on Windows
    promptly instead of waiting for GC, preventing handle exhaustion across
    hundreds of tests that each create file-based WAL databases."""
    yield
    for db_file in tmp_path.rglob("*.db"):
        try:
            import sqlite3 as _sqlite3
            _conn = _sqlite3.connect(str(db_file))
            _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _conn.close()
        except Exception:
            pass


@pytest.fixture
def sample_session_state(mock_anthropic_client, sample_scene, temp_project_dir, sample_indexes, sample_learning_data):
    """Create a sample SessionState for testing (no DB connection)."""
    scene_path = temp_project_dir / "chapter01.md"
    return SessionState(
        client=mock_anthropic_client,
        scene_content=sample_scene,
        scene_path=str(scene_path),
        project_path=temp_project_dir,
        indexes=sample_indexes,
        learning=sample_learning_data,
    )


# --- Phase 2: Management test fixtures ---

@pytest.fixture
def real_novel_dir():
    """Path to the Dorian Gray test corpus for integration tests.

    Skips the test if no chapter text files are present (i.e. the user
    hasn't populated the directory yet).
    """
    p = Path(__file__).parent / "fixtures" / "novels" / "picture-of-dorian-gray"
    if not p.exists():
        pytest.skip("Test corpus directory not found: tests/fixtures/novels/picture-of-dorian-gray/")
    txt_files = sorted(p.glob("chapter-*.txt"))
    if not txt_files:
        pytest.skip("No chapter files in test corpus — see tests/fixtures/novels/picture-of-dorian-gray/README.md")
    return p


@pytest.fixture
def sample_session_summary():
    """Mock SessionSummary data for testing."""
    return {
        'id': 1,
        'scene_path': '/test/scene01.txt',
        'status': 'completed',
        'model': 'sonnet',
        'created_at': '2026-02-10T10:00:00',
        'completed_at': '2026-02-10T10:30:00',
        'total_findings': 5,
        'accepted_count': 3,
        'rejected_count': 2,
        'withdrawn_count': 0,
    }


@pytest.fixture
def sample_session_detail():
    """Mock SessionDetail with findings."""
    return {
        'id': 1,
        'scene_path': '/test/scene01.txt',
        'status': 'completed',
        'model': 'sonnet',
        'created_at': '2026-02-10T10:00:00',
        'completed_at': '2026-02-10T10:30:00',
        'total_findings': 2,
        'accepted_count': 1,
        'rejected_count': 1,
        'withdrawn_count': 0,
        'findings': [
            {
                'number': 1,
                'severity': 'critical',
                'lens': 'prose',
                'location': 'Paragraph 1',
                'evidence': 'Test evidence',
                'impact': 'Test impact',
                'options': ['Fix it'],
                'status': 'accepted',
                'line_start': 5,
                'line_end': 10,
            },
            {
                'number': 2,
                'severity': 'major',
                'lens': 'structure',
                'location': 'Scene opening',
                'evidence': 'Missing goal',
                'impact': 'Reader confusion',
                'options': ['Add goal'],
                'status': 'rejected',
                'line_start': 1,
                'line_end': 3,
            },
        ],
    }


@pytest.fixture
def sample_learning_with_ids():
    """Learning data with entry IDs for deletion tests."""
    return {
        'project_name': 'Test Novel',
        'review_count': 3,
        'preferences': [
            {'id': 1, 'description': '[prose] Sentence fragments OK'},
            {'id': 2, 'description': '[structure] Prefer shorter scenes'},
        ],
        'blind_spots': [
            {'id': 3, 'description': '[clarity] Pronoun ambiguity'},
        ],
        'resolutions': [
            {'id': 4, 'description': 'Finding #5 — fixed'},
        ],
        'ambiguity_intentional': [
            {'id': 5, 'description': 'Dream sequence'},
        ],
        'ambiguity_accidental': [
            {'id': 6, 'description': 'Unclear referent (fixed)'},
        ],
    }
