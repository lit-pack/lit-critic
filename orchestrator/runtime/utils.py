"""
Utility functions for the lit-critic system.

Provides:
- Line numbering for scene text (enabling line-number-aware locations)
- Diff-based line mapping for scene change detection
- Finding line adjustment after edits
"""

import difflib
import re
from pathlib import Path
from typing import Optional

from .models import Finding


SCENE_BOUNDARY_PREFIX = "===== SCENE BOUNDARY: "


def concatenate_scenes(scene_docs: list[tuple[str, str]]) -> tuple[str, list[dict]]:
    """Concatenate ordered scene docs into one analysis text with line mapping.

    Returns ``(concatenated_text, line_map)`` where ``line_map`` entries contain
    global/local line boundaries for each scene region in the concatenated text.
    """
    concatenated_lines: list[str] = []
    line_map: list[dict] = []
    global_line = 1

    for idx, (scene_path, scene_text) in enumerate(scene_docs):
        scene_name = Path(scene_path).name
        marker = f"{SCENE_BOUNDARY_PREFIX}{scene_name} ====="
        concatenated_lines.append(marker)
        marker_line = global_line
        global_line += 1

        scene_lines = scene_text.splitlines()
        local_start = 1 if scene_lines else None
        local_end = len(scene_lines) if scene_lines else None
        global_start = global_line if scene_lines else None
        global_end = global_line + len(scene_lines) - 1 if scene_lines else None

        if scene_lines:
            concatenated_lines.extend(scene_lines)
            global_line = global_end + 1

        line_map.append(
            {
                "scene_path": scene_path,
                "scene_name": scene_name,
                "marker_line": marker_line,
                "global_start": global_start,
                "global_end": global_end,
                "local_start": local_start,
                "local_end": local_end,
            }
        )

        if idx < len(scene_docs) - 1:
            concatenated_lines.append("")
            global_line += 1

    return "\n".join(concatenated_lines), line_map


def map_global_range_to_scene(
    line_map: list[dict], line_start: Optional[int], line_end: Optional[int]
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """Map concatenated/global line range back to owning scene/local lines."""
    if not line_map:
        return None, line_start, line_end

    if line_start is None:
        return line_map[0].get("scene_path"), None, None

    end = line_end if line_end is not None else line_start

    for entry in line_map:
        start = entry.get("global_start")
        finish = entry.get("global_end")
        if start is None or finish is None:
            continue
        if start <= line_start <= finish:
            local_start = line_start - start + 1
            local_end = end - start + 1
            if local_end < local_start:
                local_end = local_start
            return entry.get("scene_path"), local_start, local_end if line_end is not None else None

    return line_map[-1].get("scene_path"), line_start, line_end


def remap_location_line_range(
    location: str,
    line_start: Optional[int],
    line_end: Optional[int],
) -> str:
    """Rewrite the first ``Lx`` / ``Lx-Ly`` range in *location* to canonical lines.

    This keeps any descriptive suffix intact, e.g.::

        "L120-L124, starting '... '" -> "L12-L16, starting '... '"

    If no line numbers are available, or no ``L``-prefixed range is present,
    returns *location* unchanged.
    """
    if not location or line_start is None:
        return location

    target = f"L{line_start}"
    if line_end is not None and line_end != line_start:
        target = f"L{line_start}-L{line_end}"

    pattern = re.compile(r"L\d+(?:\s*-\s*L?\d+)?")
    if not pattern.search(location):
        return location
    return pattern.sub(target, location, count=1)


def number_lines(text: str) -> str:
    """Prepend line numbers to each line of text.

    Format: ``L001: first line``, ``L002: second line``, etc.
    The width of the number is determined by the total number of lines
    so that all prefixes align.

    This is used in prompts so that Claude can see and reference line numbers.
    """
    lines = text.split('\n')
    width = max(len(str(len(lines))), 3)
    return '\n'.join(
        f"L{i + 1:0{width}d}: {line}"
        for i, line in enumerate(lines)
    )


# ---------------------------------------------------------------------------
# Diff-based line mapping
# ---------------------------------------------------------------------------

def compute_line_mapping(old_text: str, new_text: str) -> dict:
    """Compute how line numbers shifted between two versions of a text.

    Uses ``difflib.SequenceMatcher`` to align old and new lines.

    Returns a dict with:
        mapping  – ``{old_line: new_line}`` for lines that survived unchanged
                   (1-based line numbers on both sides).
        deleted  – ``set`` of old line numbers that were deleted or replaced.
        inserted – ``set`` of new line numbers that are entirely new.
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)

    mapping: dict[int, int] = {}
    deleted: set[int] = set()
    inserted: set[int] = set()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for offset in range(i2 - i1):
                mapping[i1 + offset + 1] = j1 + offset + 1  # 1-based
        elif tag == 'delete':
            for i in range(i1, i2):
                deleted.add(i + 1)
        elif tag == 'replace':
            for i in range(i1, i2):
                deleted.add(i + 1)
            for j in range(j1, j2):
                inserted.add(j + 1)
        elif tag == 'insert':
            for j in range(j1, j2):
                inserted.add(j + 1)

    return {"mapping": mapping, "deleted": deleted, "inserted": inserted}


def adjust_finding_lines(finding: Finding, line_mapping: dict) -> str:
    """Adjust a finding's ``line_start`` / ``line_end`` using a line mapping.

    Returns a status string:
        ``"adjusted"`` – lines shifted successfully to new positions.
        ``"stale"``    – finding's line range overlaps an edited/deleted region;
                         the finding needs re-evaluation.
        ``"no_lines"`` – finding has no line numbers (cannot adjust).
    """
    if finding.line_start is None:
        return "no_lines"

    mapping = line_mapping["mapping"]
    deleted = line_mapping["deleted"]

    end = finding.line_end if finding.line_end is not None else finding.line_start
    finding_lines = range(finding.line_start, end + 1)

    # If any line in the finding's range was deleted/replaced, it's stale
    if any(line in deleted for line in finding_lines):
        finding.stale = True
        return "stale"

    # Try to map both endpoints
    new_start = mapping.get(finding.line_start)
    new_end = mapping.get(end)

    if new_start is None:
        finding.stale = True
        return "stale"

    finding.line_start = new_start
    finding.line_end = new_end if finding.line_end is not None else None
    return "adjusted"


def apply_scene_change(findings: list[Finding], old_text: str, new_text: str,
                       start_index: int = 0) -> dict:
    """Detect a scene change and adjust all remaining findings.

    Computes the diff between *old_text* and *new_text*, then adjusts
    ``line_start``/``line_end`` for every finding from *start_index* onward
    that has not already been processed (i.e. status is ``"pending"`` or any
    active status).

    Returns a summary dict:
        adjusted  – number of findings whose lines were shifted
        stale     – number of findings marked stale (need re-evaluation)
        no_lines  – number of findings without line numbers
        total     – total findings examined
    """
    line_mapping = compute_line_mapping(old_text, new_text)

    summary = {"adjusted": 0, "stale": 0, "no_lines": 0, "total": 0}

    for finding in findings[start_index:]:
        summary["total"] += 1
        result = adjust_finding_lines(finding, line_mapping)
        summary[result] += 1

    return summary
