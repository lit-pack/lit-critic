"""Deterministic code-check stage functions and orchestrator.

All stages have the signature:
    stage(scene_text: str, indexes: dict[str, str]) -> list[dict]

The orchestrator collects stage outputs, numbers them sequentially, and
returns a list of Finding objects with origin="code".
"""

from .orchestrator import run_code_checks
from .stages import (
    index_crossref,
    meta_validate,
    scene_index_match,
    style_patterns,
    timeline_validate,
)

__all__ = [
    "run_code_checks",
    "meta_validate",
    "index_crossref",
    "scene_index_match",
    "timeline_validate",
    "style_patterns",
]
