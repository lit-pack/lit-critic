"""Stateless core orchestration service (text/context in, structured out)."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from contracts.v1.adapters import (
    adapt_legacy_analyze_output_to_response,
    adapt_legacy_re_evaluate_output_to_response,
)
from contracts.v1.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ReEvaluateFindingRequest,
    ReEvaluateFindingResponse,
)

from .adapters.legacy_runtime import (
    LegacyAnalysisEngineAdapter,
    LegacyDiscussionEngineAdapter,
    LegacyReEvaluationEngineAdapter,
)
from .domain import AnalysisSnapshot, CoreFinding
from .ports import AnalysisEnginePort, DiscussionEnginePort, ReEvaluationEnginePort

# Explanation prompt — used for the one-shot "Explain This" feature.
_EXPLAIN_AUTHOR_MESSAGE = (
    "Please explain in 2-3 sentences why this specific finding was flagged "
    "and what the author might consider doing about it. "
    "Be direct, concise, and avoid jargon."
)


_ANALYSIS_ENGINE: AnalysisEnginePort = LegacyAnalysisEngineAdapter()
_DISCUSSION_ENGINE: DiscussionEnginePort = LegacyDiscussionEngineAdapter()
_RE_EVALUATION_ENGINE: ReEvaluationEnginePort = LegacyReEvaluationEngineAdapter()


def _model_used(model_name: str) -> str:
    """Report model id/label used for request metadata."""
    return model_name


def _to_server_indexes(indexes: dict[str, str | None]) -> dict[str, str]:
    mapping = {
        "CANON": "CANON.md",
        "CAST": "cast",
        "GLOSSARY": "glossary",
        "STYLE": "STYLE.md",
        "THREADS": "threads",
        "TIMELINE": "timeline",
    }
    return {legacy: (indexes.get(contract) or "") for contract, legacy in mapping.items()}


async def analyze(
    request: AnalyzeRequest,
    *,
    client,
    analysis_engine: AnalysisEnginePort | None = None,
) -> AnalyzeResponse:
    """Run stateless analysis against scene/index text payload."""
    started = time.perf_counter()
    engine = analysis_engine or _ANALYSIS_ENGINE
    legacy_output = await engine.analyze(
        client=client,
        scene_text=request.scene_text,
        indexes=_to_server_indexes(request.indexes.model_dump()),
        model=request.model_settings.analysis_model,
        max_tokens=request.model_settings.max_tokens,
    )
    elapsed = time.perf_counter() - started
    return adapt_legacy_analyze_output_to_response(
        legacy_output,
        model_used=_model_used(request.model_settings.analysis_model),
        timings={"total_seconds": elapsed},
    )


async def explain_finding(
    finding_dict: dict[str, Any],
    scene_text: str,
    *,
    client,
    model: str,
    max_tokens: int = 1024,
    discussion_engine: DiscussionEnginePort | None = None,
) -> str:
    """Generate a one-shot explanation for a finding.

    Sends a single LLM query with the finding context and scene excerpt.
    No state change, no discussion history, no learning signal.

    Args:
        finding_dict: Serialised finding (same shape as CoreFinding.to_dict).
        scene_text: The relevant scene text for context.
        client: Resolved LLM provider client.
        model: Model identifier string.
        max_tokens: Token budget for the response (default 1 K — explanations are brief).
        discussion_engine: Injectable engine (defaults to _DISCUSSION_ENGINE).

    Returns:
        The explanation text produced by the model.
    """
    engine = discussion_engine or _DISCUSSION_ENGINE
    finding = CoreFinding.from_dict(finding_dict)

    # Reuse the discussion engine with the fixed explain prompt.
    # The engine already handles scene + finding context assembly.
    response_text, _status, _updated_finding = await engine.discuss(
        discussion_client=client,
        scene_text=scene_text,
        finding=finding,
        author_message=_EXPLAIN_AUTHOR_MESSAGE,
        model=model,
        max_tokens=max_tokens,
    )
    return response_text


async def re_evaluate(
    request: ReEvaluateFindingRequest,
    *,
    client,
    re_evaluation_engine: ReEvaluationEnginePort | None = None,
) -> ReEvaluateFindingResponse:
    """Re-evaluate a stale finding against updated scene text (stateless)."""
    started = time.perf_counter()
    finding = CoreFinding.from_dict(request.stale_finding.model_dump())
    engine = re_evaluation_engine or _RE_EVALUATION_ENGINE
    legacy_output = await engine.re_evaluate(
        client=client,
        finding=finding,
        updated_scene_text=request.updated_scene_text,
        model=request.model_settings.analysis_model,
        max_tokens=request.model_settings.max_tokens,
    )
    elapsed = time.perf_counter() - started
    return adapt_legacy_re_evaluate_output_to_response(
        legacy_output,
        model_used=_model_used(request.model_settings.analysis_model),
        original_finding=finding.to_dict(include_state=False),
        timings={"total_seconds": elapsed},
    )


# ---------------------------------------------------------------------------
# Behavioral signal extraction (Phase E1)
# ---------------------------------------------------------------------------

#: Minimum number of consecutive analysis runs in which a finding must appear
#: as ``active`` (not silenced) before it is recorded as a blind spot.
_PERSISTENT_RUN_THRESHOLD = 3


def extract_behavioral_signals(
    conn: sqlite3.Connection,
    snapshot: AnalysisSnapshot,
    project_path: Path | None = None,
    *,
    persistent_run_threshold: int = _PERSISTENT_RUN_THRESHOLD,
) -> dict[str, int]:
    """Extract learning signals from behavioral patterns in *snapshot* and write them to the DB.

    Three signal types per feasibility §7.1:

    1. **Silenced findings** → ``preferences``
       A finding with ``state="silenced"`` means the author has explicitly
       dismissed this type of feedback.  Stored with confidence 0.5 (first
       silence) or escalated to 0.7 when the same pattern has been silenced
       before (indicating a sustained stylistic choice).

    2. **Resolved findings** → ``resolutions``
       Findings from the *previous* snapshot that are now marked
       ``state="resolved"`` (their underlying text changed and the issue
       disappeared).  These signal that the author noticed the feedback and
       acted on it.

    3. **Persistent active findings** → ``blind spots``
       A finding that has appeared as ``active`` in at least
       *persistent_run_threshold* distinct snapshots for the same scene
       indicates the author has seen it repeatedly and chosen not to act.
       Stored as a blind spot entry when the threshold is first reached.

    No duplicate entries are written — descriptions are checked against
    existing ``learning_entry`` rows before inserting.

    Args:
        conn: Open SQLite connection for the project database.
        snapshot: The *just-completed* analysis snapshot (must have ``id`` set).
        project_path: Optional absolute project root for path relativisation.
        persistent_run_threshold: Number of runs before recording a blind spot.

    Returns:
        Counts of new entries written: ``{"preferences": N, "resolutions": N, "blind_spots": N}``.
    """
    from orchestrator.persistence.learning_store import LearningStore  # local import avoids circular deps

    counts: dict[str, int] = {"preferences": 0, "resolutions": 0, "blind_spots": 0}

    if snapshot.id is None:
        return counts

    # -----------------------------------------------------------------------
    # 1. Silenced findings → preferences
    # -----------------------------------------------------------------------
    for finding in snapshot.findings:
        if finding.state != "silenced":
            continue

        desc = (
            f"[{finding.lens}] {finding.severity}: "
            f"{finding.evidence[:120].strip()}"
        )

        existing_row = conn.execute(
            "SELECT id, confidence FROM learning_entry "
            "WHERE category = 'preference' AND description = ?",
            (desc,),
        ).fetchone()

        if existing_row is not None:
            # Repeated silence on the same pattern → escalate confidence.
            current = float(existing_row["confidence"] or 0.5)
            escalated = min(0.9, current + 0.2)
            if escalated > current:
                LearningStore.update_confidence(conn, existing_row["id"], escalated)
        else:
            LearningStore.add_preference(conn, desc, confidence=0.5)
            counts["preferences"] += 1

    # -----------------------------------------------------------------------
    # 2. Resolved findings → resolutions
    # Look at the previous snapshot for this scene and collect findings that
    # were ``active`` or ``silenced`` there but are now ``resolved`` in the DB.
    # -----------------------------------------------------------------------
    for scene_path in snapshot.scene_paths:
        rel_path = _to_relative_path(scene_path, project_path)
        pattern = f'%"{rel_path}"%'

        prev_row = conn.execute(
            """SELECT id FROM analysis_snapshot
               WHERE scene_paths LIKE ? AND id < ?
               ORDER BY created_at DESC LIMIT 1""",
            (pattern, snapshot.id),
        ).fetchone()

        if prev_row is None:
            continue

        prev_snapshot_id = prev_row["id"]

        resolved_rows = conn.execute(
            """SELECT lens, severity, evidence
               FROM snapshot_finding
               WHERE snapshot_id = ? AND state = 'resolved'""",
            (prev_snapshot_id,),
        ).fetchall()

        for row in resolved_rows:
            desc = (
                f"[{row['lens']}] resolved {row['severity']}: "
                f"{(row['evidence'] or '')[:120].strip()}"
            )
            existing = conn.execute(
                "SELECT id FROM learning_entry "
                "WHERE category = 'resolution' AND description = ?",
                (desc,),
            ).fetchone()
            if existing is None:
                LearningStore.add_resolution(conn, desc)
                counts["resolutions"] += 1

    # -----------------------------------------------------------------------
    # 3. Persistent active findings → blind spots
    # Count distinct snapshots where the same correlation_key appears as 'active'.
    # -----------------------------------------------------------------------
    for finding in snapshot.findings:
        if finding.state != "active" or not finding.correlation_key:
            continue

        count_row = conn.execute(
            """SELECT COUNT(DISTINCT sf.snapshot_id) AS run_count
               FROM snapshot_finding sf
               WHERE sf.correlation_key = ? AND sf.state = 'active'""",
            (finding.correlation_key,),
        ).fetchone()

        run_count = int(count_row["run_count"]) if count_row else 0
        if run_count < persistent_run_threshold:
            continue

        desc = (
            f"[{finding.lens}] persistent {finding.severity}: "
            f"{finding.evidence[:120].strip()}"
        )
        existing = conn.execute(
            "SELECT id FROM learning_entry "
            "WHERE category = 'blind_spot' AND description = ?",
            (desc,),
        ).fetchone()
        if existing is None:
            LearningStore.add_blind_spot(conn, desc)
            counts["blind_spots"] += 1

    conn.commit()
    return counts


# ---------------------------------------------------------------------------
# Contrarian lens (Phase G1) — anti-sycophancy meta-analysis
# ---------------------------------------------------------------------------

#: Lens name used to identify contrarian-lens silence rules.
_CONTRARIAN_LENS_NAME = "contrarian"

#: Description used when the contrarian lens itself is silenced.
_CONTRARIAN_SILENCED_DESC = (
    "[POLICY] contrarian lens silenced — author has disabled anti-sycophancy meta-analysis"
)

#: Minimum occurrences before a silence/persistence pattern is considered significant.
_CONTRARIAN_MIN_PATTERN_COUNT = 3


async def run_contrarian_lens(
    conn: sqlite3.Connection,
    llm_client: Any,
    model_id: str,
    project_path: Path | None = None,  # noqa: ARG001
    *,
    min_pattern_count: int = _CONTRARIAN_MIN_PATTERN_COUNT,
) -> list[dict[str, Any]]:
    """Run the contrarian lens analysis and return project-level meta-findings.

    The contrarian lens examines the author's sustained behavioral patterns —
    heavily silenced categories and findings that persist unaddressed across
    many analysis runs — and produces meta-findings that surface cases where
    that avoidance may be masking genuine literary weaknesses.

    Per feasibility §9.3:

    * Runs **only during deep analysis** — the caller must enforce this.
    * Uses the ``frontier`` model slot — the caller passes the resolved
      *model_id*.
    * If the contrarian lens is silenced via a category silence rule, the
      silencing is recorded prominently in the learning data and an empty
      list is returned.

    Args:
        conn: Open SQLite connection for the project database.
        llm_client: Resolved LLM client (frontier tier).
        model_id: Resolved frontier model identifier.
        project_path: Currently unused; reserved for future path handling.
        min_pattern_count: Minimum occurrences before a pattern is considered
            significant enough to report.

    Returns:
        List of meta-finding dicts — same key shape as standard findings:
        ``lens``, ``severity``, ``location``, ``evidence``, ``impact``,
        ``options``.  All findings are project-level (no line numbers).
    """
    # -----------------------------------------------------------------------
    # 1. Check if the contrarian lens is category-silenced.
    # -----------------------------------------------------------------------
    silenced_row = conn.execute(
        """SELECT 1 FROM silence_rule
           WHERE rule_type = 'category'
             AND lens IN (?, 'all')
             AND suspended = 0
           LIMIT 1""",
        (_CONTRARIAN_LENS_NAME,),
    ).fetchone()

    if silenced_row:
        _record_contrarian_lens_silenced(conn)
        return []

    # -----------------------------------------------------------------------
    # 2. Gather significant patterns.
    # -----------------------------------------------------------------------
    patterns = _gather_contrarian_patterns(conn, min_count=min_pattern_count)

    if not patterns["silence_by_lens"] and not patterns["persistent_findings"]:
        # No patterns significant enough to report.
        return []

    # -----------------------------------------------------------------------
    # 3. Build prompt and call LLM.
    # -----------------------------------------------------------------------
    prompt = _build_contrarian_prompt(patterns)

    try:
        response = await llm_client.create_message(
            model=model_id,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.text.strip()
    except Exception:  # noqa: BLE001
        return []

    # -----------------------------------------------------------------------
    # 4. Parse response into meta-findings.
    # -----------------------------------------------------------------------
    return _parse_contrarian_findings(raw_text)


def _gather_contrarian_patterns(
    conn: sqlite3.Connection,
    *,
    min_count: int = _CONTRARIAN_MIN_PATTERN_COUNT,
) -> dict[str, Any]:
    """Query the DB for significant silence and persistence patterns.

    Returns a dict with:
    ``silence_by_lens``:  list of {lens, count} rows where count ≥ min_count.
    ``persistent_findings``: list of {lens, evidence, run_count} rows where
        the same finding has appeared in at least min_count distinct snapshots.
    """
    silence_rows = conn.execute(
        """SELECT lens, COUNT(*) AS count
           FROM silence_rule
           WHERE suspended = 0
             AND lens IS NOT NULL AND lens != ''
             AND lens != ?
           GROUP BY lens
           HAVING count >= ?
           ORDER BY count DESC""",
        (_CONTRARIAN_LENS_NAME, min_count),
    ).fetchall()

    persistent_rows = conn.execute(
        """SELECT lens, evidence, COUNT(DISTINCT snapshot_id) AS run_count
           FROM snapshot_finding
           WHERE state = 'active'
             AND correlation_key IS NOT NULL
             AND correlation_key != ''
           GROUP BY correlation_key
           HAVING run_count >= ?
           ORDER BY run_count DESC
           LIMIT 10""",
        (min_count,),
    ).fetchall()

    return {
        "silence_by_lens": [dict(r) for r in silence_rows],
        "persistent_findings": [dict(r) for r in persistent_rows],
    }


def _build_contrarian_prompt(patterns: dict[str, Any]) -> str:
    """Build the LLM prompt for contrarian lens analysis."""

    def _fmt_silence(rows: list[dict]) -> str:
        if not rows:
            return "[none]"
        return "\n".join(
            f"  - {r['lens']}: silenced {r['count']} time(s)" for r in rows
        )

    def _fmt_persistent(rows: list[dict]) -> str:
        if not rows:
            return "[none]"
        return "\n".join(
            f"  - [{r['lens']}] \"{(r['evidence'] or '')[:80]}\" — {r['run_count']} consecutive runs"
            for r in rows
        )

    return (
        "You are performing a contrarian editorial analysis. Your job is to look at an\n"
        "author's behavioral patterns and identify where sustained avoidance of feedback\n"
        "may be masking genuine weaknesses in their writing.\n\n"
        "INPUT DATA:\n\n"
        f"Silenced feedback by category (how many times this lens has been silenced):\n"
        f"{_fmt_silence(patterns['silence_by_lens'])}\n\n"
        f"Findings the author has consistently left unaddressed across multiple runs:\n"
        f"{_fmt_persistent(patterns['persistent_findings'])}\n\n"
        "TASK:\n"
        "Based on the patterns above, identify 1-3 genuine literary concerns that the\n"
        "author may be systematically avoiding. For each concern, produce a meta-finding.\n\n"
        "Each finding must be project-level (not about any single scene), direct, and\n"
        "evidence-based. Do NOT be diplomatic. If a pattern suggests a structural weakness,\n"
        "name it plainly.\n\n"
        "IMPORTANT — output format:\n"
        'Return a JSON array of objects. Each object must have exactly these keys:\n'
        '  "severity": one of "critical", "major", "minor"\n'
        '  "evidence": a 1-2 sentence statement of the pattern observed\n'
        '  "impact": a 1-sentence statement of the likely literary consequence\n'
        '  "options": an array of 1-3 concrete suggestions\n\n'
        "Return ONLY the JSON array. No preamble, no explanation, no markdown fences."
    )


def _parse_contrarian_findings(raw_text: str) -> list[dict[str, Any]]:
    """Parse the LLM response into a list of meta-finding dicts.

    Attempts strict JSON parsing; returns an empty list on any error rather
    than raising (the contrarian lens is optional — parse failures should not
    crash the analysis run).
    """
    import json  # noqa: PLC0415

    # Strip any accidental markdown fences.
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(data, list):
        return []

    findings: list[dict[str, Any]] = []
    valid_severities = {"critical", "major", "minor"}

    for item in data:
        if not isinstance(item, dict):
            continue

        severity = str(item.get("severity", "minor")).lower()
        if severity not in valid_severities:
            severity = "minor"

        evidence = str(item.get("evidence", "")).strip()
        if not evidence:
            continue  # skip empty findings

        findings.append({
            "lens": _CONTRARIAN_LENS_NAME,
            "severity": severity,
            "location": "[project-level]",
            "line_start": None,
            "line_end": None,
            "scene_path": None,
            "evidence": evidence,
            "impact": str(item.get("impact", "")).strip(),
            "options": [str(o) for o in item.get("options", []) if o],
            "flagged_by": [_CONTRARIAN_LENS_NAME],
            "ambiguity_type": None,
            "stale": False,
            "state": "active",
        })

    return findings


def _record_contrarian_lens_silenced(conn: sqlite3.Connection) -> None:
    """Record that the contrarian lens was silenced, prominently in learning data.

    This is the anti-sycophancy transparency mechanism: if the author silences
    the contrarian lens, that fact is preserved in the learning data so it
    surfaces in the editorial profile and informs future profile synthesis.
    """
    from orchestrator.persistence.learning_store import LearningStore  # local import

    # Check if we already have this entry to avoid duplicates.
    existing = conn.execute(
        "SELECT id FROM learning_entry WHERE category = 'preference' AND description = ?",
        (_CONTRARIAN_SILENCED_DESC,),
    ).fetchone()

    if existing is None:
        # Use max confidence (0.9) — this is a deliberate policy decision.
        LearningStore.add_preference(conn, _CONTRARIAN_SILENCED_DESC, confidence=0.9)
        conn.commit()


def _to_relative_path(scene_path: str, project_path: Path | None) -> str:
    """Return *scene_path* relative to *project_path* for use in LIKE queries.

    When *project_path* is given, the path is made relative to it.
    When *project_path* is None:
    - If *scene_path* is already relative, it is returned as-is (POSIX slashes)
      so the LIKE pattern matches the relative paths stored in the DB.
    - If *scene_path* is absolute, fall back to the basename (best-effort).
    """
    from pathlib import PurePosixPath  # noqa: PLC0415

    if project_path:
        try:
            return str(Path(scene_path).relative_to(project_path))
        except ValueError:
            pass

    p = Path(scene_path)
    if not p.is_absolute():
        # Already relative — normalise to POSIX slashes to match what SnapshotStore stores.
        return PurePosixPath(p).as_posix()
    # Absolute path without a known project root — the basename is all we can match on.
    return p.name


# ---------------------------------------------------------------------------
# Silence rules → editorial profile (Phase E2)
# ---------------------------------------------------------------------------

#: Confidence assigned to pattern-type silence rules (sustained stylistic choice).
_PATTERN_RULE_CONFIDENCE = 0.7

#: Confidence assigned to category-type silence rules (deliberate editorial policy).
_CATEGORY_RULE_CONFIDENCE = 0.9


def build_silence_rule_preferences(
    conn: sqlite3.Connection,
    project_path: Path | None = None,  # noqa: ARG001 — reserved for future path normalization
) -> dict[str, int]:
    """Convert active silence rules into learning preference entries.

    Silence *rules* (explicit policy decisions: "silence all pacing findings
    in Act 2") are separate from silenced *findings* (individual dismissed
    instances handled by ``extract_behavioral_signals``).  This function
    bridges the two so that editorial profile synthesis reflects the author's
    sustained editorial policies, not just incidental finding-level dismissals.

    Rule types and their mapped confidence:

    * ``instance`` — not converted: too specific to represent a stylistic pattern.
    * ``pattern``  — confidence 0.7 (sustained choice, high signal).
    * ``category`` — confidence 0.9 (deliberate lens-level policy, very high signal).

    Descriptions follow the format::

        [POLICY] silence <rule_type> — <lens>/<severity>: <text_pattern_or_note>

    so they are clearly distinguishable from finding-level preferences in the
    learning data and the synthesized editorial profile.

    Args:
        conn: Open SQLite connection for the project database.
        project_path: Currently unused; reserved for future path normalization.

    Returns:
        Counts: ``{"preferences_added": N, "preferences_updated": N}``.
    """
    from orchestrator.persistence.learning_store import LearningStore  # local import avoids circular deps

    counts = {"preferences_added": 0, "preferences_updated": 0}

    # Only pattern and category rules carry stylistic-pattern signal.
    rows = conn.execute(
        """SELECT rule_type, scope, lens, severity, text_pattern, note
           FROM silence_rule
           WHERE suspended = 0 AND rule_type IN ('pattern', 'category')
           ORDER BY rule_type, lens""",
    ).fetchall()

    if not rows:
        return counts

    for row in rows:
        rule_type = row["rule_type"]
        lens = row["lens"] or "all"
        severity = row["severity"] or "any"
        text_pattern = row["text_pattern"] or ""
        note = row["note"] or ""
        scope = row["scope"] or "project"

        # Build a human-readable description for the learning entry.
        detail_parts = []
        if text_pattern:
            detail_parts.append(f'pattern: "{text_pattern[:80]}"')
        if note:
            detail_parts.append(f'note: "{note[:80]}"')
        detail = "; ".join(detail_parts) if detail_parts else "no detail"

        scope_label = "project-wide" if scope == "project" else "scene"
        desc = (
            f"[POLICY] silence {rule_type} ({scope_label}) — "
            f"{lens}/{severity}: {detail}"
        )

        confidence = (
            _CATEGORY_RULE_CONFIDENCE
            if rule_type == "category"
            else _PATTERN_RULE_CONFIDENCE
        )

        existing_row = conn.execute(
            "SELECT id, confidence FROM learning_entry "
            "WHERE category = 'preference' AND description = ?",
            (desc,),
        ).fetchone()

        if existing_row is not None:
            # Rule still active; escalate confidence if it has grown.
            current = float(existing_row["confidence"] or 0.5)
            if confidence > current:
                LearningStore.update_confidence(conn, existing_row["id"], confidence)
                counts["preferences_updated"] += 1
        else:
            LearningStore.add_preference(conn, desc, confidence=confidence)
            counts["preferences_added"] += 1

    conn.commit()
    return counts
