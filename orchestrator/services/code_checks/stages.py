"""Deterministic code-check stage functions.

Each stage has the signature:
    stage(scene_text: str, indexes: dict[str, str]) -> list[dict]

Returns a list of partial finding dicts.  The orchestrator fills in the
`number` field and wraps each dict in a Finding object with origin="code".

Line numbers in returned dicts are 1-based and relative to the full
scene_text string (including the @@META block), so they map correctly onto
the concatenated scene_content used in the analysis pipeline.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared regex patterns
# ---------------------------------------------------------------------------

_META_START_RE = re.compile(r"^@@META\s*$", re.MULTILINE)
_META_END_RE   = re.compile(r"^@@END\s*$", re.MULTILINE)
_ID_PATTERN    = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
_SCENE_REF_PATTERN = re.compile(r"^([^\r\n]+\.txt|\d{1,4}\.\d{1,4}\.\d{1,4})$", re.IGNORECASE)
_SCENE_ID_RE   = re.compile(r"\b(\d{1,4}\.\d{1,4}\.\d{1,4})\b")
_PLACEHOLDER_RE = re.compile(r"\[TODO\]|\[TBD\]|\bTBD\b", re.IGNORECASE)
_FIELD_HEADER_RE = re.compile(r"^(?:\s*-\s*)?\*\*([^*:]+):\*\*\s*(.*)$")
_REL_ITEM_RE   = re.compile(r"^\s*-\s+(\w[\w\s]*?):", re.MULTILINE)

# Recommended @@META fields (lowercase)
_META_RECOMMENDED = [
    "id", "part", "chapter", "scene", "chrono", "pov", "tense", "location",
    "cast", "objective", "threats", "secrets", "contanchors", "terms",
    "threads", "prev", "next",
]
_META_NULLISH_VALUES = {"", "none", "tbd", "n/a"}

_TEMPLATE_META_BLOCK_HEADING_RE = re.compile(r"^#{2,6}\s+meta\s+block\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _norm_heading(text: str) -> str:
    """Normalise a heading for case/whitespace-insensitive comparison."""
    return re.sub(r"\s+", " ", text.strip()).lower()


def _norm_meta_key(field_name: str) -> str:
    """Normalise a META key for case/whitespace-insensitive matching."""
    cleaned = field_name.strip().strip("*").strip().strip("`")
    cleaned = re.sub(r"\s*\.\s*", ".", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower()


def _parse_meta_block(scene_text: str) -> tuple[str | None, dict[str, str]]:
    """Extract the @@META block and parse key-value fields.

    Returns (raw_meta_block, fields_dict).
    raw_meta_block is None if no valid block was found.
    Fields are keyed by their lowercase name.
    """
    m_start = _META_START_RE.search(scene_text)
    m_end   = _META_END_RE.search(scene_text)
    if not m_start or not m_end or m_end.start() <= m_start.end():
        return None, {}

    raw = scene_text[m_start.end():m_end.start()]
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        colon = line.find(":")
        if colon > 0:
            key = line[:colon].strip().lstrip("-").strip()
            val = line[colon + 1:].strip()
            if key:
                fields[_norm_meta_key(key)] = val
    return raw, fields


def _extract_template_meta_block(template_text: str) -> str | None:
    """Extract fenced META Block content from TEMPLATE.md when present."""
    lines = template_text.splitlines()
    heading_index: int | None = None
    for i, line in enumerate(lines):
        if _TEMPLATE_META_BLOCK_HEADING_RE.match(line.strip()):
            heading_index = i
            break

    if heading_index is None:
        return None

    i = heading_index + 1
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("```"):
            i += 1
            block_lines: list[str] = []
            while i < len(lines):
                if lines[i].strip().startswith("```"):
                    block = "\n".join(block_lines).strip()
                    return block or None
                block_lines.append(lines[i])
                i += 1
            block = "\n".join(block_lines).strip()
            return block or None

        if re.match(r"^#{1,6}\s+", stripped):
            break
        i += 1

    return None


def _parse_template_meta_keys(template_meta_block: str) -> set[str]:
    """Parse META key names from TEMPLATE.md META Block fenced content."""
    keys: set[str] = set()

    for line in template_meta_block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.upper() in {"@@META", "@@END"}:
            continue
        if ":" not in stripped:
            continue

        key = stripped.split(":", 1)[0]
        key = re.sub(r"^(?:[-*]\s*)+", "", key).strip()
        key_norm = _norm_meta_key(key)
        if key_norm:
            keys.add(key_norm)

    return keys


def _template_meta_recommended_fields(indexes: dict[str, str]) -> set[str] | None:
    """Return recommended META keys extracted from TEMPLATE.md, if parseable."""
    template_text = indexes.get("TEMPLATE.md") or ""
    if not template_text:
        return None

    template_meta_block = _extract_template_meta_block(template_text)
    if not template_meta_block:
        return None

    template_keys = _parse_template_meta_keys(template_meta_block)
    return template_keys or None


def _meta_alias_items(fields: dict[str, str], terminal_key: str) -> list[tuple[str, str]]:
    """Return (field_key, value) pairs whose terminal key matches `terminal_key`."""
    wanted = _norm_meta_key(terminal_key).split(".")[-1]
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for field_key, value in fields.items():
        if field_key.split(".")[-1] != wanted:
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        pair = (field_key, cleaned)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    return pairs


def _meta_field_label(field_key: str) -> str:
    """Format a normalized meta field key for human-facing messages."""
    return ".".join(part.capitalize() for part in field_key.split("."))


def _iter_meta_list_values(
    fields: dict[str, str],
    terminal_key: str,
) -> list[tuple[str, str, str]]:
    """Split semicolon/comma separated META alias values into normalized items."""
    items: list[tuple[str, str, str]] = []
    for field_key, raw_value in _meta_alias_items(fields, terminal_key):
        for raw_item in re.split(r"[;,]", raw_value):
            item = raw_item.strip()
            if item:
                items.append((field_key, raw_value, item))
    return items


def _find_first_meta_alias_value(fields: dict[str, str], terminal_key: str) -> tuple[str, str] | None:
    """Return the first (field_key, value) pair for a terminal META alias key."""
    items = _meta_alias_items(fields, terminal_key)
    return items[0] if items else None


def _is_nullish_meta_value(value: str) -> bool:
    return value.strip().lower() in _META_NULLISH_VALUES


def _split_h3_entries(content: str) -> list[tuple[str, int, str]]:
    """Return [(heading_text, line_no, entry_text), ...] for ### headings."""
    lines = content.splitlines()
    starts: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("### "):
            starts.append((i, s[4:].strip()))
    out: list[tuple[str, int, str]] = []
    for idx, (start_i, heading) in enumerate(starts):
        end_i = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        out.append((heading, start_i + 1, "\n".join(lines[start_i:end_i]).strip()))
    return out


def _extract_field_value(entry_text: str, field_name: str) -> str:
    """Extract the value of a **FieldName:** line from a ### entry block."""
    wanted = field_name.strip().lower()
    for ln in entry_text.splitlines():
        m = _FIELD_HEADER_RE.match(ln.strip())
        if m and m.group(1).strip().lower() == wanted:
            return m.group(2).strip()
    return ""


def _extract_timeline_scene_ids(timeline_text: str) -> set[str]:
    """Return the set of scene IDs (NN.NN.NN) bolded in the timeline index."""
    return {m.group(1) for m in re.finditer(r"\*\*(\d{1,4}\.\d{1,4}\.\d{1,4})\*\*", timeline_text)}


def _extract_relationship_targets(cast_entry_text: str) -> list[str]:
    """Extract relationship target names from a CAST entry block."""
    lines = cast_entry_text.splitlines()
    in_relationships = False
    targets: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        m_field = _FIELD_HEADER_RE.match(stripped)
        if m_field:
            in_relationships = m_field.group(1).strip().lower() == "relationships"
            continue
        if not in_relationships:
            continue
        if stripped.startswith("### ") or stripped.startswith("## "):
            break
        m_rel = _REL_ITEM_RE.match(ln)
        if m_rel:
            targets.append(m_rel.group(1).strip())
    return targets


def _section_for_line(content: str, line_number: int, section_level: int = 2) -> str:
    """Return the nearest preceding section heading at the given markdown level."""
    lines = content.splitlines()
    prefix = "#" * section_level + " "
    for i in range(min(line_number - 1, len(lines) - 1), -1, -1):
        s = lines[i].strip()
        if s.startswith(prefix):
            return s
    return ""


def _finding(
    *,
    severity: str,
    lens: str,
    location: str,
    evidence: str,
    impact: str,
    options: list[str] | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
) -> dict[str, Any]:
    """Build a partial finding dict for use by the orchestrator."""
    return {
        "severity": severity,
        "lens": lens,
        "location": location,
        "line_start": line_start,
        "line_end": line_end,
        "evidence": evidence,
        "impact": impact,
        "options": options or [],
        "flagged_by": [lens],
        "ambiguity_type": None,
        "stale": False,
        "origin": "code",
    }


# ---------------------------------------------------------------------------
# Stage 1: meta_validate
# ---------------------------------------------------------------------------

def meta_validate(scene_text: str, indexes: dict[str, str]) -> list[dict]:
    """Validate only @@META structure and Prev/Next pointer formatting.

    Args:
        scene_text: Full text of the scene file (including @@META block).
        indexes: Project index files (not used by this stage, present for
            uniform stage signature).

    Returns:
        List of finding dicts.  Empty list means the scene is clean.
    """
    del indexes  # Stage keeps a uniform signature but does not use indexes.

    findings: list[dict] = []
    LENS = "meta_validate"

    m_start = _META_START_RE.search(scene_text)
    m_end   = _META_END_RE.search(scene_text)

    if not m_start:
        findings.append(_finding(
            severity="critical",
            lens=LENS,
            location="Scene file (start)",
            evidence="No @@META marker found.",
            impact="The scene metadata block cannot be parsed.",
            options=["Add a @@META block at the top of the scene file (see scene-format guide)."],
        ))
        return findings  # No point checking further

    if not m_end or m_end.start() <= m_start.end():
        findings.append(_finding(
            severity="critical",
            lens=LENS,
            location="@@META block",
            evidence="@@META marker found but no matching @@END marker.",
            impact="The metadata block is unclosed; tooling cannot parse it.",
            options=["Add @@END on its own line after the last metadata field."],
        ))
        return findings

    _raw, fields = _parse_meta_block(scene_text)

    for ptr_field in ("prev", "next"):
        ptr_items = _meta_alias_items(fields, ptr_field)
        if not ptr_items:
            findings.append(_finding(
                severity="major",
                lens=LENS,
                location="@@META block",
                evidence=f"Required navigation field '{ptr_field.upper()}' is missing.",
                impact="Scene ordering links cannot be validated without this field.",
                options=[
                    f"Add '{ptr_field.upper()}: <filename>' to the @@META block, "
                    "or use None / TBD if there is no adjacent scene.",
                ],
            ))
            continue

        for field_key, ptr_val in ptr_items:
            value = ptr_val.strip()
            if _is_nullish_meta_value(value):
                continue
            if not _SCENE_REF_PATTERN.match(value):
                findings.append(_finding(
                    severity="major",
                    lens=LENS,
                    location=f"@@META → {_meta_field_label(field_key)}: {ptr_val}",
                    evidence=(
                        f"Pointer {_meta_field_label(field_key)} value '{ptr_val}' has an invalid format."
                    ),
                    impact="Invalid Prev/Next formatting can break ordering validation.",
                    options=[
                        f"Use a scene filename in {_meta_field_label(field_key)}, or set it to None / TBD.",
                    ],
                ))

    return findings


# ---------------------------------------------------------------------------
# Stage 2: index_crossref
# ---------------------------------------------------------------------------

def index_crossref(scene_text: str, indexes: dict[str, str]) -> list[dict]:
    """Cross-reference index documents for internal consistency.

    Checks: duplicate headings, missing required fields, orphan scene
    references, thread status mismatches, glossary casing, placeholder
    census, and partial character name usage.

    Args:
        scene_text: Full scene text (not used by this stage but present for
            uniform signature).
        indexes: Project index files.

    Returns:
        List of finding dicts.
    """
    findings: list[dict] = []
    LENS = "index_crossref"

    relevant = ["CANON.md", "cast", "glossary", "threads", "timeline"]
    existing = {k: (indexes.get(k) or "") for k in relevant if (indexes.get(k) or "").strip()}

    timeline_text = existing.get("timeline", "")
    timeline_scene_ids = _extract_timeline_scene_ids(timeline_text) if timeline_text else set()

    # ------------------------------------------------------------------ #
    # Placeholder census — one finding per file that contains placeholders
    # ------------------------------------------------------------------ #
    for filename in relevant:
        text = indexes.get(filename) or ""
        count = len(_PLACEHOLDER_RE.findall(text))
        if count > 0:
            findings.append(_finding(
                severity="minor",
                lens=LENS,
                location=filename,
                evidence=f"{count} placeholder(s) found ([TODO] / [TBD] / TBD).",
                impact="Index entries with placeholders may produce incomplete analysis results.",
                options=[f"Fill in the placeholder entries in {filename}."],
            ))

    # ------------------------------------------------------------------ #
    # Duplicate ### headings within each file
    # ------------------------------------------------------------------ #
    for filename, text in existing.items():
        seen: dict[str, tuple[str, int]] = {}
        for m in re.finditer(r"^###\s+(.+)$", text, re.MULTILINE):
            heading  = m.group(1).strip()
            line_no  = text[: m.start()].count("\n") + 1
            key = _norm_heading(heading)
            if key in seen:
                first_heading, first_line = seen[key]
                findings.append(_finding(
                    severity="critical",
                    lens=LENS,
                    location=f"{filename} → ### {heading} (lines {first_line} and {line_no})",
                    evidence=(
                        f"Duplicate heading \"{first_heading}\" found "
                        f"at lines {first_line} and {line_no}."
                    ),
                    impact="Duplicate entries cause ambiguous cross-references.",
                    options=[
                        f"Remove or rename one of the duplicate '### {heading}' entries in {filename}.",
                    ],
                ))
            else:
                seen[key] = (heading, line_no)

    # ------------------------------------------------------------------ #
    # Missing required fields per file type
    # ------------------------------------------------------------------ #
    required_by_file: dict[str, list[str]] = {
        "cast":     ["Role", "Relationships"],
        "glossary": ["Definition", "First seen"],
        "threads":  ["Opened", "Status"],
    }
    for filename, required_fields in required_by_file.items():
        text = existing.get(filename, "")
        if not text:
            continue
        for heading, _line_no, entry in _split_h3_entries(text):
            lower_entry = entry.lower()
            for req in required_fields:
                if req.lower() not in lower_entry:
                    findings.append(_finding(
                        severity="major",
                        lens=LENS,
                        location=f"{filename} → ### {heading}",
                        evidence=f"Missing expected field: '{req}'.",
                        impact="Incomplete index entries reduce analysis accuracy.",
                        options=[f"Add '**{req}:** ...' to the '{heading}' entry in {filename}."],
                    ))

    # ------------------------------------------------------------------ #
    # Orphan 'First seen' references (CAST + GLOSSARY → TIMELINE)
    # ------------------------------------------------------------------ #
    if timeline_scene_ids:
        for filename in ("cast", "glossary"):
            text = existing.get(filename, "")
            if not text:
                continue
            for heading, _line_no, entry in _split_h3_entries(text):
                for scene_id in re.findall(
                    r"First seen:\s*(\d{1,4}\.\d{1,4}\.\d{1,4})", entry, re.IGNORECASE
                ):
                    if scene_id not in timeline_scene_ids:
                        findings.append(_finding(
                            severity="major",
                            lens=LENS,
                            location=f"{filename} → ### {heading} → First seen: {scene_id}",
                            evidence=(
                                f"Scene {scene_id} referenced in 'First seen' "
                                f"does not appear in the timeline."
                            ),
                            impact="Orphan scene reference may indicate a deleted scene or typo.",
                            options=[
                                f"Add scene {scene_id} to the timeline, or",
                                f"Correct the 'First seen' value in {filename}.",
                            ],
                        ))

    # ------------------------------------------------------------------ #
    # Orphan thread 'Opened' references (THREADS → TIMELINE)
    # ------------------------------------------------------------------ #
    if timeline_scene_ids and existing.get("threads"):
        for heading, _line_no, entry in _split_h3_entries(existing["threads"]):
            opened = _extract_field_value(entry, "Opened")
            m = _SCENE_ID_RE.search(opened)
            if m:
                sid = m.group(1)
                if sid not in timeline_scene_ids:
                    findings.append(_finding(
                        severity="major",
                        lens=LENS,
                        location=f"Threads → ### {heading} → Opened: {sid}",
                        evidence=(
                            f"Scene {sid} referenced in 'Opened' "
                            "does not appear in the timeline."
                        ),
                        impact="Orphan scene reference may indicate a deleted scene or typo.",
                        options=[
                            f"Add scene {sid} to the timeline, or",
                            "Correct the 'Opened' field in Threads.",
                        ],
                    ))

    # ------------------------------------------------------------------ #
    # Orphan relationship targets (CAST → CAST)
    # ------------------------------------------------------------------ #
    cast_text = existing.get("cast", "")
    if cast_text:
        cast_headings     = [h for h, _ln, _e in _split_h3_entries(cast_text)]
        cast_headings_lwr = [h.lower() for h in cast_headings]
        for heading, _line_no, entry in _split_h3_entries(cast_text):
            for target in _extract_relationship_targets(entry):
                t = target.strip().lower()
                if not t:
                    continue
                matches = [h for h in cast_headings_lwr if h == t or h.startswith(t + " ")]
                if not matches:
                    findings.append(_finding(
                        severity="minor",
                        lens=LENS,
                    location=f"Characters → {heading} → Relationships: {target}",
                    evidence=f"Relationship target \"{target}\" has no matching extracted character entry.",
                    impact=(
                        "Relationship cross-references may be incomplete or misspelled."
                    ),
                    options=[
                        f"Add '{target}' to extracted characters, or",
                            f"Correct the relationship target in '{heading}'s entry.",
                        ],
                    ))

    # ------------------------------------------------------------------ #
    # Thread status vs containing section (THREADS)
    # ------------------------------------------------------------------ #
    threads_text = existing.get("threads", "")
    if threads_text:
        for heading, line_no, entry in _split_h3_entries(threads_text):
            status  = _extract_field_value(entry, "Status").lower()
            section = _section_for_line(threads_text, line_no, section_level=2).lower()
            raw_status = _extract_field_value(entry, "Status")

            if "active threads" in section and ("resolved" in status or "closed" in status):
                findings.append(_finding(
                    severity="critical",
                    lens=LENS,
                    location=f"Threads → ### {heading}",
                    evidence=(
                        f"Thread is under '## Active Threads' "
                        f"but Status is '{raw_status}'."
                    ),
                    impact="Inconsistent thread status misleads continuity analysis.",
                    options=[
                        "Move the thread entry to '## Resolved Threads', or",
                        "Update its Status field to 'Active'.",
                    ],
                ))
            elif "resolved threads" in section and "active" in status:
                findings.append(_finding(
                    severity="critical",
                    lens=LENS,
                    location=f"Threads → ### {heading}",
                    evidence=(
                        f"Thread is under '## Resolved Threads' "
                        f"but Status is '{raw_status}'."
                    ),
                    impact="Inconsistent thread status misleads continuity analysis.",
                    options=[
                        "Move the thread entry to '## Active Threads', or",
                        "Update its Status field to 'Resolved'.",
                    ],
                ))

    # ------------------------------------------------------------------ #
    # Glossary term casing (terms marked 'Always capitalized')
    # ------------------------------------------------------------------ #
    glossary_text = existing.get("glossary", "")
    if glossary_text:
        other_files = {
            name: existing[name]
            for name in ("cast", "threads", "timeline", "CANON.md")
            if name in existing
        }
        for heading, _line_no, entry in _split_h3_entries(glossary_text):
            notes = _extract_field_value(entry, "Notes")
            if "always capitalized" not in notes.lower():
                continue
            canonical = heading.strip()
            if not canonical:
                continue
            pat = re.compile(re.escape(canonical), re.IGNORECASE)
            for filename, text in other_files.items():
                mismatch = None
                for m in pat.finditer(text):
                    seen_word = m.group(0)
                    if seen_word != canonical:
                        mismatch = seen_word
                        break
                if mismatch:
                    findings.append(_finding(
                        severity="major",
                        lens=LENS,
                    location=f"Glossary → {canonical} (referenced in {filename})",
                    evidence=(
                        f"Glossary Notes say 'Always capitalized' "
                        f"but found '{mismatch}' in {filename}."
                    ),
                        impact="Inconsistent capitalisation of defined terms.",
                        options=[f"Replace '{mismatch}' with '{canonical}' in {filename}."],
                    ))

    # ------------------------------------------------------------------ #
    # Partial character name usage in THREADS / TIMELINE
    # ------------------------------------------------------------------ #
    if cast_text:
        cast_names = [h for h, _ln, _e in _split_h3_entries(cast_text)]
        for target_file in ("threads", "timeline"):
            text = existing.get(target_file, "")
            if not text:
                continue
            for full_name in cast_names:
                tokens = full_name.split()
                if len(tokens) < 2:
                    continue
                first = tokens[0]
                if re.search(rf"\b{re.escape(full_name)}\b", text):
                    continue  # Full name found — no issue
                first_matches = re.findall(rf"\b{re.escape(first)}\b", text)
                if not first_matches:
                    continue
                if target_file == "timeline" and len(first_matches) > 1:
                    # Frequent timeline shorthand (e.g., repeated protagonist first-name labels)
                    # is treated as canonical index style and should not be flagged.
                    continue
                findings.append(_finding(
                    severity="minor",
                    lens=LENS,
                    location=f"{target_file} mentions '{first}'",
                    evidence=(
                        f"Closest CAST match for '{first}' is '{full_name}' "
                        f"(partial name used in {target_file})."
                    ),
                    impact=(
                        "Inconsistent name usage may indicate a different character "
                        "or a continuity oversight."
                    ),
                    options=[
                        f"Replace '{first}' with the full name '{full_name}' in {target_file}, or",
                        "Verify this is the intended character reference.",
                    ],
                ))

    return findings


# ---------------------------------------------------------------------------
# Stage 3: scene_index_match
# ---------------------------------------------------------------------------

def scene_index_match(scene_text: str, indexes: dict[str, str]) -> list[dict]:
    """No-op stage retained for backward compatibility.

    Scene/index cross-references moved to knowledge refresh flow.
    """
    del scene_text, indexes
    return []


# ---------------------------------------------------------------------------
# Stage 4: timeline_validate
# ---------------------------------------------------------------------------

def _scene_tuple(scene_id: str) -> tuple[int, ...]:
    return tuple(int(x) for x in scene_id.split("."))


def timeline_validate(scene_text: str, indexes: dict[str, str]) -> list[dict]:
    """Validate scene ordering and @@META timeline pointers against the timeline index.

    Checks:
        1. Scene IDs are in ascending numeric order within each chapter block.
        2. The current scene's ID (from @@META) is listed in the timeline index.
        3. Prev / Next pointers reference scenes that exist in the timeline index.

    Args:
        scene_text: Full text of the scene file.
        indexes: Project index files.

    Returns:
        List of finding dicts.
    """
    findings: list[dict] = []
    LENS = "timeline_validate"

    timeline_text = indexes.get("timeline") or ""
    _raw, fields = _parse_meta_block(scene_text)
    timeline_scene_ids = _extract_timeline_scene_ids(timeline_text) if timeline_text else set()

    # ------------------------------------------------------------------ #
    # 1. Scene ordering within chapter blocks
    # ------------------------------------------------------------------ #
    if timeline_text:
        lines = timeline_text.splitlines()
        current_chapter = ""
        prev_scene: tuple[int, ...] | None = None
        prev_scene_id = ""
        for ln in lines:
            s = ln.strip()
            if s.startswith("### "):
                current_chapter = s
                prev_scene = None
                prev_scene_id = ""
                continue
            m = re.search(r"\*\*(\d{1,4}\.\d{1,4}\.\d{1,4})\*\*", s)
            if not m:
                continue
            sid = m.group(1)
            cur = _scene_tuple(sid)
            if prev_scene is not None and cur < prev_scene:
                findings.append(_finding(
                    severity="major",
                    lens=LENS,
                    location=(
                        f"Timeline → {current_chapter or 'Timeline'} → **{sid}**"
                    ),
                    evidence=(
                        f"Scene {sid} appears after {prev_scene_id} "
                        "but has a lower numeric ID."
                    ),
                    impact=(
                        "Out-of-order scene entries may indicate a sequencing error "
                        "or a mis-numbered scene."
                    ),
                    options=[
                        f"Reorder scene {sid} before {prev_scene_id} in the timeline, or",
                        "Verify the scene IDs are correct.",
                    ],
                ))
            prev_scene = cur
            prev_scene_id = sid

    # ------------------------------------------------------------------ #
    # 2. Current scene's ID should exist in the timeline index
    # ------------------------------------------------------------------ #
    if fields and timeline_text:
        id_pair = _find_first_meta_alias_value(fields, "id")
        scene_id = id_pair[1].strip() if id_pair else ""
        id_label = _meta_field_label(id_pair[0]) if id_pair else "ID"
        if scene_id and _ID_PATTERN.match(scene_id):
            if scene_id not in timeline_scene_ids:
                findings.append(_finding(
                    severity="major",
                    lens=LENS,
                    location=f"@@META → {id_label}: {scene_id}",
                    evidence=f"Scene {scene_id} is not listed in the timeline.",
                    impact="Unlisted scenes are invisible to timeline-based cross-references.",
                    options=[
                        f"Add scene {scene_id} to the timeline under the appropriate chapter.",
                    ],
                ))

    # ------------------------------------------------------------------ #
    # 3. Prev / Next pointer consistency
    # ------------------------------------------------------------------ #
    if fields:
        for ptr_field in ("prev", "next"):
            ptr_items = _meta_alias_items(fields, ptr_field)
            if not ptr_items:
                findings.append(_finding(
                    severity="major",
                    lens=LENS,
                    location="@@META block",
                    evidence=f"Required navigation field '{ptr_field.upper()}' is missing.",
                    impact="Broken navigation pointers make reading order validation incomplete.",
                    options=[
                        f"Add '{ptr_field.upper()}: <filename>' to @@META, "
                        "or use None / TBD if there is no adjacent scene.",
                    ],
                ))
                continue

            for field_key, ptr_val in ptr_items:
                if _is_nullish_meta_value(ptr_val):
                    continue

                m = _SCENE_ID_RE.search(ptr_val)
                if not m:
                    # A plain filename reference (e.g. scene-A.txt) is valid even without
                    # an embedded NN.NN.NN scene ID — skip the timeline cross-check.
                    if _SCENE_REF_PATTERN.match(ptr_val.strip()):
                        continue
                    findings.append(_finding(
                        severity="major",
                        lens=LENS,
                        location=f"@@META → {_meta_field_label(field_key)}: {ptr_val}",
                        evidence=(
                            f"Pointer {_meta_field_label(field_key)} value '{ptr_val}' "
                            "is not a valid scene reference (expected a filename or None / TBD)."
                        ),
                        impact="Invalid pointer formatting breaks navigation chain validation.",
                        options=[
                            f"Use a scene filename in '{_meta_field_label(field_key)}', "
                            "or set it to None / TBD.",
                        ],
                    ))
                    continue

                ref_id = m.group(1)
                if timeline_scene_ids and ref_id not in timeline_scene_ids:
                    findings.append(_finding(
                        severity="major",
                        lens=LENS,
                        location=f"@@META → {_meta_field_label(field_key)}: {ptr_val}",
                        evidence=(
                            f"Pointer {_meta_field_label(field_key)} references scene {ref_id} "
                            "which is not in the timeline."
                        ),
                        impact="Broken Prev/Next pointers disrupt reading order tracking.",
                        options=[
                            f"Add scene {ref_id} to the timeline, or",
                            f"Correct the {_meta_field_label(field_key)} pointer value.",
                        ],
                    ))

    return findings


# ---------------------------------------------------------------------------
# Stage 5: style_patterns
# ---------------------------------------------------------------------------

# Regex for detecting explicit "never use" / "avoid" rules in STYLE.md
_STYLE_RULE_RE = re.compile(
    r'(?:never use|avoid|do not use|don\'t use|forbidden[:\s]+)\s+"([^"]+)"',
    re.IGNORECASE,
)


def style_patterns(scene_text: str, indexes: dict[str, str]) -> list[dict]:
    """Detect mechanical style violations using regex patterns.

    Checks:
        1. Double (or extra) spaces in the prose.
        2. Explicit "never use X" / "avoid X" rules defined in STYLE.md.

    Line numbers in returned findings are 1-based relative to the full
    scene_text (so they map correctly onto the concatenated scene content).

    Args:
        scene_text: Full text of the scene file.
        indexes: Project index files (STYLE.md used when present).

    Returns:
        List of finding dicts.
    """
    findings: list[dict] = []
    LENS = "style_patterns"

    # Determine where prose starts (line after @@END, 0-based index)
    lines = scene_text.splitlines()
    prose_start_idx = 0  # 0-based; if no @@END found, treat whole file as prose
    for i, ln in enumerate(lines):
        if ln.strip() == "@@END":
            prose_start_idx = i + 1
            break

    if prose_start_idx >= len(lines):
        return findings  # No prose content

    # ------------------------------------------------------------------ #
    # 1. Double (extra) spaces in prose lines
    # ------------------------------------------------------------------ #
    double_space_re = re.compile(r"  +")
    double_space_lines: list[int] = []
    for line_idx in range(prose_start_idx, len(lines)):
        stripped = lines[line_idx].lstrip()
        if double_space_re.search(stripped):
            double_space_lines.append(line_idx + 1)  # 1-based global line number

    if double_space_lines:
        count  = len(double_space_lines)
        sample = double_space_lines[:3]
        sample_str = ", ".join(str(n) for n in sample)
        if count > 3:
            sample_str += "..."
        findings.append(_finding(
            severity="minor",
            lens=LENS,
            location=f"Scene prose (lines {sample_str})",
            evidence=(
                f"Double or extra spaces found on {count} prose line(s)."
            ),
            impact=(
                "Extra whitespace may indicate copy-paste artifacts "
                "or formatting inconsistencies."
            ),
            options=["Find-and-replace multiple spaces with a single space in the scene."],
            line_start=double_space_lines[0],
            line_end=double_space_lines[-1],
        ))

    # ------------------------------------------------------------------ #
    # 2. STYLE.md explicit pattern rules
    # ------------------------------------------------------------------ #
    style_text = indexes.get("STYLE.md") or ""
    if style_text:
        prose_lines_with_nos = [
            (line_idx + 1, lines[line_idx])
            for line_idx in range(prose_start_idx, len(lines))
        ]
        _check_style_md_rules(prose_lines_with_nos, style_text, findings, LENS)

    return findings


def _check_style_md_rules(
    prose_lines_with_nos: list[tuple[int, str]],
    style_text: str,
    findings: list[dict],
    lens: str,
) -> None:
    """Parse STYLE.md for 'never use X' rules and check prose against them.

    Args:
        prose_lines_with_nos: List of (1-based line number, line text) pairs
            for the prose portion of the scene.
        style_text: Content of STYLE.md.
        findings: Mutable list to append finding dicts to.
        lens: Lens name to set on generated findings.
    """
    for m in _STYLE_RULE_RE.finditer(style_text):
        pattern_text = m.group(1).strip()
        if not pattern_text:
            continue
        try:
            pat = re.compile(re.escape(pattern_text), re.IGNORECASE)
        except re.error:
            continue

        hit_lines: list[int] = []
        for line_no, line in prose_lines_with_nos:
            if pat.search(line):
                hit_lines.append(line_no)

        if hit_lines:
            count  = len(hit_lines)
            sample = hit_lines[:3]
            sample_str = ", ".join(str(n) for n in sample)
            if count > 3:
                sample_str += "..."
            findings.append(_finding(
                severity="major",
                lens=lens,
                location=f"Scene prose (lines {sample_str})",
                evidence=(
                    f"STYLE.md forbids \"{pattern_text}\" "
                    f"but it appears {count} time(s) in the prose."
                ),
                impact="Violates an explicit style rule defined in STYLE.md.",
                options=[
                    f"Remove or replace all occurrences of \"{pattern_text}\" in the scene.",
                ],
                line_start=hit_lines[0],
                line_end=hit_lines[-1],
            ))
