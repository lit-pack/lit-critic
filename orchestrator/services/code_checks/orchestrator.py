"""Code-check orchestrator.

Runs all deterministic check stages in sequence, collects their finding
dicts, numbers them sequentially, and returns a list of Finding objects
with origin="code".

Any stage that raises an unexpected exception is skipped with a warning;
the pipeline continues with the remaining stages.
"""

from __future__ import annotations

import logging

from orchestrator.runtime.models import Finding
from .stages import (
    meta_validate,
    style_patterns,
)

logger = logging.getLogger(__name__)

# Ordered list of stage functions.  Add new stages here to register them.
_STAGES = [
    meta_validate,
    style_patterns,
]


def run_code_checks(scene_text: str, indexes: dict[str, str]) -> list[Finding]:
    """Run all code-check stages and return a numbered list of Findings.

    This is a synchronous, deterministic function — no LLM calls, no IO.

    Args:
        scene_text: Full text of the scene file (including @@META block).
            For multi-scene analysis this is the concatenated scene content.
        indexes: Project index files keyed by short name (e.g. "cast") or filename for author-maintained files (e.g. "CANON.md").

    Returns:
        List of Finding objects numbered sequentially from 1, all with
        origin="code".  Empty list if all checks pass.
    """
    all_dicts: list[dict] = []

    for stage in _STAGES:
        try:
            stage_findings = stage(scene_text, indexes)
            all_dicts.extend(stage_findings)
        except Exception:
            logger.warning(
                "Code-check stage '%s' raised an unexpected error — skipping.",
                stage.__name__,
                exc_info=True,
            )

    findings: list[Finding] = []
    for i, d in enumerate(all_dicts, 1):
        findings.append(Finding(
            number=i,
            severity=d.get("severity", "minor"),
            lens=d.get("lens", "code"),
            location=d.get("location", ""),
            line_start=d.get("line_start"),
            line_end=d.get("line_end"),
            evidence=d.get("evidence", ""),
            impact=d.get("impact", ""),
            options=d.get("options", []),
            flagged_by=d.get("flagged_by", ["code"]),
            ambiguity_type=d.get("ambiguity_type"),
            stale=d.get("stale", False),
            origin="code",
        ))

    return findings
