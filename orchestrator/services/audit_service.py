"""Index file audit service.

Provides a two-layer audit pipeline:
- Deterministic checks (pure Python, no IO/LLM)
- Semantic contradiction checks (LLM tool call)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from orchestrator.runtime.api import run_index_audit, run_lens
from orchestrator.runtime.config import DEFAULT_MODEL, MAX_TOKENS
from orchestrator.runtime.models import Finding
from orchestrator.services.code_checks.orchestrator import run_code_checks


_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
_FIELD_HEADER_RE = re.compile(r"^(?:\s*-\s*)?\*\*([^*:]+):\*\*\s*(.*)$")
_SCENE_ID_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{2})\b")
_REL_ITEM_RE = re.compile(r"^\s*-\s+(\w[\w\s]*?):", re.MULTILINE)
_PLACEHOLDER_RE = re.compile(r"\[TODO\]|\[TBD\]|\bTBD\b", re.IGNORECASE)


@dataclass
class AuditFinding:
    check_id: str
    severity: str  # error | warning | info
    file: str
    location: str
    message: str
    related_file: str | None = None


@dataclass
class AuditReport:
    deterministic: list[AuditFinding] = field(default_factory=list)
    semantic: list[AuditFinding] = field(default_factory=list)
    placeholder_census: dict[str, int] = field(default_factory=dict)


def _norm_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def _split_h3_entries(content: str) -> list[tuple[str, int, str]]:
    """Return [(heading_text, line_no, entry_text), ...] for ### entries."""
    lines = content.splitlines()
    starts: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith("### "):
            starts.append((i, stripped[4:].strip()))

    out: list[tuple[str, int, str]] = []
    for idx, (start_i, heading) in enumerate(starts):
        end_i = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        out.append((heading, start_i + 1, "\n".join(lines[start_i:end_i]).strip()))
    return out


def _extract_field_value(entry_text: str, field_name: str) -> str:
    wanted = field_name.strip().lower()
    for ln in entry_text.splitlines():
        m = _FIELD_HEADER_RE.match(ln.strip())
        if not m:
            continue
        if m.group(1).strip().lower() == wanted:
            return m.group(2).strip()
    return ""


def _extract_timeline_scene_ids(timeline_text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"\*\*(\d{2}\.\d{2}\.\d{2})\*\*", timeline_text)]


def _extract_relationship_targets(cast_entry_text: str) -> list[str]:
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
    """Return nearest preceding section heading at the requested markdown level."""
    lines = content.splitlines()
    for i in range(min(line_number - 1, len(lines) - 1), -1, -1):
        s = lines[i].strip()
        if s.startswith("#" * section_level + " "):
            return s
    return ""


def _scene_tuple(scene_id: str) -> tuple[int, int, int]:
    a, b, c = scene_id.split(".")
    return int(a), int(b), int(c)


def audit_indexes_deterministic(indexes: dict[str, str]) -> AuditReport:
    """Run all deterministic consistency checks. No LLM, no IO."""
    report = AuditReport()

    relevant = ["CANON.md", "cast", "glossary", "threads", "timeline"]
    existing = {k: (indexes.get(k) or "") for k in relevant if (indexes.get(k) or "").strip()}

    for filename in relevant:
        text = indexes.get(filename) or ""
        report.placeholder_census[filename] = len(_PLACEHOLDER_RE.findall(text))

    timeline_text = existing.get("timeline", "")
    timeline_scene_ids = set(_extract_timeline_scene_ids(timeline_text)) if timeline_text else set()

    # duplicate_heading (### within each file)
    for filename, text in existing.items():
        seen: dict[str, tuple[str, int]] = {}
        for m in re.finditer(r"^###\s+(.+)$", text, re.MULTILINE):
            heading = m.group(1).strip()
            line_no = text[: m.start()].count("\n") + 1
            key = _norm_heading(heading)
            if key in seen:
                first_heading, first_line = seen[key]
                report.deterministic.append(
                    AuditFinding(
                        check_id="duplicate_heading",
                        severity="error",
                        file=filename,
                        location=f"### {heading}",
                        message=(
                            f"Duplicate heading \"{first_heading}\" found "
                            f"(lines {first_line} and {line_no})."
                        ),
                    )
                )
            else:
                seen[key] = (heading, line_no)

    # missing_required_fields
    required_by_file = {
        "cast": ["Role", "Relationships"],
        "glossary": ["Definition", "First seen"],
        "threads": ["Opened", "Status"],
    }
    for filename, required_fields in required_by_file.items():
        text = existing.get(filename, "")
        if not text:
            continue
        for heading, _line_no, entry in _split_h3_entries(text):
            lower_entry = entry.lower()
            for req in required_fields:
                if req.lower() not in lower_entry:
                    report.deterministic.append(
                        AuditFinding(
                            check_id="missing_required_fields",
                            severity="warning",
                            file=filename,
                            location=f"### {heading}",
                            message=f"Missing expected field: {req}",
                        )
                    )

    # orphan_first_seen (CAST + GLOSSARY -> TIMELINE)
    if timeline_scene_ids:
        for filename in ("cast", "glossary"):
            text = existing.get(filename, "")
            if not text:
                continue
            for heading, _line_no, entry in _split_h3_entries(text):
                for scene_id in re.findall(r"First seen:\s*(\d{2}\.\d{2}\.\d{2})", entry, re.IGNORECASE):
                    if scene_id not in timeline_scene_ids:
                        report.deterministic.append(
                            AuditFinding(
                                check_id="orphan_first_seen",
                                severity="warning",
                                file=filename,
                                location=f"### {heading} → First seen: {scene_id}",
                                message=f"Scene {scene_id} does not exist in the timeline",
                                related_file="Timeline",
                            )
                        )

    # orphan_thread_opened (THREADS -> TIMELINE)
    if timeline_scene_ids and existing.get("threads"):
        for heading, _line_no, entry in _split_h3_entries(existing["threads"]):
            opened = _extract_field_value(entry, "Opened")
            m = _SCENE_ID_RE.search(opened)
            if m:
                scene_id = m.group(1)
                if scene_id not in timeline_scene_ids:
                    report.deterministic.append(
                        AuditFinding(
                            check_id="orphan_thread_opened",
                            severity="warning",
                            file="Threads",
                            location=f"### {heading} → Opened: {scene_id}",
                            message=f"Scene {scene_id} does not exist in the timeline",
                            related_file="Timeline",
                        )
                    )

    # orphan_relationship_target (CAST Relationships references)
    cast_text = existing.get("cast", "")
    if cast_text:
        cast_headings = [h for h, _ln, _entry in _split_h3_entries(cast_text)]
        cast_headings_lower = [h.lower() for h in cast_headings]
        for heading, _line_no, entry in _split_h3_entries(cast_text):
            for target in _extract_relationship_targets(entry):
                t = target.strip().lower()
                if not t:
                    continue
                matches = [h for h in cast_headings_lower if h == t or h.startswith(t + " ")]
                if not matches:
                    report.deterministic.append(
                        AuditFinding(
                            check_id="orphan_relationship_target",
                            severity="info",
                            file="Characters",
                            location=f"### {heading} → Relationships: {target}",
                            message=f"Relationship target \"{target}\" has no matching extracted character entry.",
                            related_file="Characters",
                        )
                    )

    # thread_status_vs_section (THREADS internal consistency)
    threads_text = existing.get("threads", "")
    if threads_text:
        for heading, line_no, entry in _split_h3_entries(threads_text):
            status = _extract_field_value(entry, "Status").lower()
            section = _section_for_line(threads_text, line_no, section_level=2).lower()
            if "active threads" in section and ("resolved" in status or "closed" in status):
                report.deterministic.append(
                    AuditFinding(
                        check_id="thread_status_vs_section",
                        severity="error",
                        file="Threads",
                        location=f"### {heading}",
                        message="Thread is under \"## Active Threads\" but Status indicates resolved/closed.",
                    )
                )
            if "resolved threads" in section and "active" in status:
                report.deterministic.append(
                    AuditFinding(
                        check_id="thread_status_vs_section",
                        severity="error",
                        file="Threads",
                        location=f"### {heading}",
                        message="Thread is under \"## Resolved Threads\" but Status indicates active.",
                    )
                )

    # timeline_scene_ordering (within each chapter)
    if timeline_text:
        lines = timeline_text.splitlines()
        current_chapter = ""
        prev_scene: tuple[int, int, int] | None = None
        prev_scene_id = ""
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("### "):
                current_chapter = s
                prev_scene = None
                prev_scene_id = ""
                continue
            m = re.search(r"\*\*(\d{2}\.\d{2}\.\d{2})\*\*", s)
            if not m:
                continue
            sid = m.group(1)
            cur = _scene_tuple(sid)
            if prev_scene is not None and cur < prev_scene:
                report.deterministic.append(
                    AuditFinding(
                        check_id="timeline_scene_ordering",
                        severity="warning",
                        file="Timeline",
                        location=f"{current_chapter or 'Timeline'} → **{sid}**",
                        message=(
                            f"Scene {sid} appears after {prev_scene_id} but is lower in numeric order."
                        ),
                    )
                )
            prev_scene = cur
            prev_scene_id = sid

    # glossary_term_casing
    glossary_text = existing.get("glossary", "")
    if glossary_text:
        other_files = {
            name: existing.get(name, "")
            for name in ("cast", "threads", "timeline", "CANON.md")
            if existing.get(name, "")
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
                    seen = m.group(0)
                    if seen != canonical:
                        mismatch = seen
                        break
                if mismatch:
                    report.deterministic.append(
                        AuditFinding(
                            check_id="glossary_term_casing",
                            severity="warning",
                            file="Glossary",
                            location=f"### {canonical}",
                            message=(
                                f"Notes say \"Always capitalized\" but found \"{mismatch}\" in {filename}."
                            ),
                            related_file=filename,
                        )
                    )

    # cast_name_in_other_files (informational partial-name usage)
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
                    continue
                if re.search(rf"\b{re.escape(first)}\b", text):
                    report.deterministic.append(
                        AuditFinding(
                            check_id="cast_name_in_other_files",
                            severity="info",
                            file=target_file,
                            location=f"{target_file} mentions \"{first}\"",
                            message=f"Closest CAST match: \"{full_name}\" (partial name)",
                            related_file="cast",
                        )
                    )

    return report


async def audit_indexes_semantic(
    indexes: dict[str, str],
    client,
    model: str = DEFAULT_MODEL,
    max_tokens: int = MAX_TOKENS,
) -> list[AuditFinding]:
    """Run LLM-based semantic contradiction detection."""
    result = await run_index_audit(
        client,
        indexes,
        model=model,
        max_tokens=max_tokens,
    )

    contradictions = result.get("contradictions", []) if isinstance(result, dict) else []
    findings: list[AuditFinding] = []

    for item in contradictions:
        try:
            severity = str(item.get("severity", "warning")).lower().strip()
            if severity not in {"error", "warning"}:
                severity = "warning"
            file_a = str(item.get("file_a", "[unknown]"))
            location_a = str(item.get("location_a", "[unknown location]"))
            file_b = str(item.get("file_b", "[unknown]"))
            claim_a = str(item.get("claim_a", ""))
            claim_b = str(item.get("claim_b", ""))
            explanation = str(item.get("explanation", "Potential contradiction detected."))

            findings.append(
                AuditFinding(
                    check_id="semantic_contradiction",
                    severity=severity,
                    file=file_a,
                    location=location_a,
                    message=(
                        f"{explanation}\n"
                        f"  Claim 1 ({file_a}): {claim_a}\n"
                        f"  Claim 2 ({file_b}): {claim_b}"
                    ),
                    related_file=file_b,
                )
            )
        except Exception:
            continue

    return findings


def audit_scene_deterministic(scene_text: str, indexes: dict[str, str]) -> list[Finding]:
    """Run deterministic scene audit checks (quick mode)."""
    return run_code_checks(scene_text, indexes)


async def audit_scene_semantic(
    scene_text: str,
    indexes: dict[str, str],
    client,
    model: str = DEFAULT_MODEL,
    max_tokens: int = MAX_TOKENS,
) -> tuple[list[Finding], str | None]:
    """Run LLM semantic scene audit checks.

    Returns semantic findings and optional error string if semantic analysis fails.
    """
    result = await run_lens(
        client,
        lens_name="continuity",
        scene=scene_text,
        indexes=indexes,
        model=model,
        max_tokens=max_tokens,
    )
    if result.error:
        return [], result.error

    semantic_findings: list[Finding] = []
    for i, finding in enumerate(result.findings, start=1):
        semantic_findings.append(
            Finding(
                number=i,
                severity=finding.get("severity", "minor"),
                lens=finding.get("lens", "continuity"),
                location=finding.get("location", ""),
                line_start=finding.get("line_start"),
                line_end=finding.get("line_end"),
                evidence=finding.get("evidence", ""),
                impact=finding.get("impact", ""),
                options=finding.get("options", []),
                flagged_by=finding.get("flagged_by", ["critic"]),
                ambiguity_type=finding.get("ambiguity_type"),
                stale=finding.get("stale", False),
                origin="critic",
            )
        )

    return semantic_findings, None


async def audit_scene(
    scene_text: str,
    indexes: dict[str, str],
    *,
    deep: bool,
    client=None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = MAX_TOKENS,
) -> dict:
    """Run scene audit in quick/deep mode with deep fallback semantics."""
    deterministic = audit_scene_deterministic(scene_text, indexes)
    semantic: list[Finding] = []
    deep_error: str | None = None

    if deep and client is not None:
        semantic, deep_error = await audit_scene_semantic(
            scene_text,
            indexes,
            client,
            model=model,
            max_tokens=max_tokens,
        )

    return {
        "deterministic": deterministic,
        "semantic": semantic,
        "deep": deep,
        "model": model,
        "deep_error": deep_error,
    }


def format_audit_report(report: AuditReport) -> str:
    """Format an AuditReport for display in CLI / VS Code."""
    lines: list[str] = ["Index Audit Report", "==================", ""]

    all_findings = list(report.deterministic)
    groups = {
        "error": [f for f in all_findings if f.severity == "error"],
        "warning": [f for f in all_findings if f.severity == "warning"],
        "info": [f for f in all_findings if f.severity == "info"],
    }

    glyph = {"error": "✗", "warning": "⚠", "info": "ℹ"}
    title = {"error": "Errors", "warning": "Warnings", "info": "Info"}

    for sev in ("error", "warning", "info"):
        bucket = groups[sev]
        lines.append(f"  {title[sev]} ({len(bucket)}):")
        for f in bucket:
            lines.append(f"    {glyph[sev]} [{f.check_id}] {f.file} → {f.location}")
            lines.append(f"      {f.message}")
        lines.append("")

    placeholder_bits = [
        f"{name}={count}" for name, count in report.placeholder_census.items() if count > 0
    ]
    if placeholder_bits:
        lines.append("  Placeholder census:")
        lines.append(f"    ℹ [placeholder_census] Placeholders: {', '.join(placeholder_bits)}")
        lines.append("")

    if report.semantic:
        lines.append(f"  Semantic Contradictions (--deep) ({len(report.semantic)}):")
        for f in report.semantic:
            lines.append(f"    ✗ {f.file} → {f.location}")
            for part in f.message.splitlines():
                lines.append(f"      {part}")
        lines.append("")

    total_errors = len(groups["error"]) + len([f for f in report.semantic if f.severity == "error"])
    total_warnings = len(groups["warning"]) + len([f for f in report.semantic if f.severity == "warning"])
    total_info = len(groups["info"]) + (1 if placeholder_bits else 0)
    lines.append(f"  Summary: {total_errors} errors, {total_warnings} warnings, {total_info} info")

    return "\n".join(lines)
