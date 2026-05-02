"""Platform-owned learning service."""

import logging
from datetime import datetime
from pathlib import Path

from orchestrator.persistence import LearningStore
from orchestrator.persistence.database import get_connection, get_passive_connection
from orchestrator.runtime.models import LearningData
from core.log_utils import op_start, op_complete

logger = logging.getLogger(__name__)

PROFILE_MIN_ENTRIES = 5
_FORBIDDEN_PHRASES = ("never flag", "always accept", "ignore", "skip")


def _get_learning_read_connection(project_path: Path, *, passive: bool):
    """Return the appropriate connection for learning read operations."""
    if passive:
        return get_passive_connection(project_path)
    return get_connection(project_path)


def load_learning(project_path: Path, passive: bool = False) -> LearningData:
    """Load learning data from SQLite, optionally avoiding import-capable startup writes."""
    conn = _get_learning_read_connection(project_path, passive=passive)
    if conn is None:
        return LearningData()

    try:
        data = LearningStore.load(conn)

        if data.get("id") is not None:
            return _dict_to_learning_data(data)

        return LearningData()
    finally:
        conn.close()


def load_learning_from_db(conn) -> LearningData:
    """Load learning data from an already-open DB connection."""
    data = LearningStore.load(conn)
    return _dict_to_learning_data(data)


def _dict_to_learning_data(data: dict) -> LearningData:
    """Convert LearningStore dict payload to ``LearningData``."""
    learning = LearningData(
        project_name=data.get("project_name", "Unknown"),
        review_count=data.get("review_count", 0),
    )
    for entry in data.get("preferences", []):
        learning.preferences.append({
            "id": entry.get("id"),
            "description": entry.get("description", str(entry)),
            "confidence": float(entry.get("confidence", 0.5)),
        })
    for entry in data.get("blind_spots", []):
        learning.blind_spots.append({
            "id": entry.get("id"),
            "description": entry.get("description", str(entry)),
        })
    for entry in data.get("resolutions", []):
        learning.resolutions.append({
            "id": entry.get("id"),
            "description": entry.get("description", str(entry)),
        })
    for entry in data.get("ambiguity_intentional", []):
        learning.ambiguity_intentional.append({
            "id": entry.get("id"),
            "description": entry.get("description", str(entry)),
        })
    for entry in data.get("ambiguity_accidental", []):
        learning.ambiguity_accidental.append({
            "id": entry.get("id"),
            "description": entry.get("description", str(entry)),
        })
    learning.editorial_profile = data.get("editorial_profile")
    return learning


def persist_learning(learning: LearningData, project_path: Path) -> None:
    """Save learning data to the project's SQLite database."""
    conn = get_connection(project_path)
    try:
        LearningStore.save_from_learning_data(conn, learning)
    finally:
        conn.close()


def persist_learning_with_conn(learning: LearningData, conn) -> None:
    """Save learning data using an already-open DB connection."""
    LearningStore.save_from_learning_data(conn, learning)


def commit_pending_learning_entries(learning: LearningData, conn) -> None:
    """Immediately write any unprocessed session learning events to ``learning_entry``.

    This is the hot path called after every user action (reject, ambiguity,
    discussion preference).  It drains the three session lists, writes each
    new entry to SQLite via ``LearningStore``, updates the in-memory
    long-term lists, and clears the processed items so subsequent calls are
    idempotent.

    ``review_count`` is intentionally *not* touched here — it is incremented
    once at session completion via ``LearningStore.increment_review_count()``.
    """
    if conn is None:
        return

    # Process rejections → preferences (with confidence increment for repeat patterns)
    for rejection in learning.session_rejections:
        if rejection.get("preference_rule"):
            desc = f"[{rejection['lens']}] {rejection['preference_rule']}"
        else:
            reason = rejection.get("reason", "no reason given")
            desc = f"[{rejection['lens']}] {rejection['pattern']} — Author says: \"{reason}\""
        # Find an existing preference whose description overlaps with this one (substring match).
        # If found, increment its confidence instead of duplicating. This breaks the preference
        # ratchet by making frequently-rejected patterns gradually more prominent (confidence ≥
        # 0.7 = HIGH) while keeping single-rejection patterns tentative (confidence 0.5 = LOW).
        existing_match = next(
            (p for p in learning.preferences
             if desc in p.get("description", "") or p.get("description", "") in desc),
            None,
        )
        if existing_match is not None:
            # Same pattern rejected again — increment confidence (cap at 0.9, never 1.0)
            if existing_match.get("id") is not None:
                new_confidence = min(0.9, float(existing_match.get("confidence", 0.5)) + 0.2)
                LearningStore.update_confidence(conn, existing_match["id"], new_confidence)
                existing_match["confidence"] = new_confidence
        else:
            # First time this pattern is rejected — create new entry at base confidence 0.5
            entry_id = LearningStore.add_preference(conn, desc, confidence=0.5)
            learning.preferences.append({"id": entry_id, "description": desc, "confidence": 0.5})
    learning.session_rejections = []  # drained

    # Process ambiguity answers → ambiguity_intentional / ambiguity_accidental
    unprocessed_ambiguity = []
    for answer in learning.session_ambiguity_answers:
        desc = f"{answer['location']}: {answer['description']}"
        if answer["intentional"]:
            if not any(desc in a.get("description", "") for a in learning.ambiguity_intentional):
                entry_id = LearningStore.add_ambiguity(conn, desc, intentional=True)
                learning.ambiguity_intentional.append({"id": entry_id, "description": desc})
        else:
            if not any(desc in a.get("description", "") for a in learning.ambiguity_accidental):
                entry_id = LearningStore.add_ambiguity(conn, desc, intentional=False)
                learning.ambiguity_accidental.append({"id": entry_id, "description": desc})
    learning.session_ambiguity_answers = unprocessed_ambiguity  # drained (always empty)

    # Process acceptances → blind spot tracking
    # Each unique lens+pattern accepted this session is stored as an "acceptance:" tracking entry.
    # One tracking entry is added per unique pattern per session (deduplication within session).
    # When tracking count reaches BLIND_SPOT_THRESHOLD, a confirmed blind_spot entry is created.
    # Tracking entries are excluded from LEARNING.md display (they are housekeeping, not content).
    BLIND_SPOT_THRESHOLD = 3
    seen_acceptance_patterns: set[str] = set()
    for acceptance in learning.session_acceptances:
        lens = acceptance.get("lens", "unknown")
        pattern = acceptance.get("pattern", "acceptance")
        desc = f"[{lens}] {pattern}"
        if desc in seen_acceptance_patterns:
            continue
        seen_acceptance_patterns.add(desc)

        # Skip if a confirmed blind spot already exists for this pattern
        if any(
            desc in bs.get("description", "")
            and not bs.get("description", "").startswith("acceptance:")
            for bs in learning.blind_spots
        ):
            continue

        # Count existing tracking entries for this pattern
        tracking_count = sum(
            1 for bs in learning.blind_spots
            if bs.get("description", "").startswith("acceptance:")
            and desc in bs.get("description", "")
        )

        # Store one tracking entry for this session's acceptance of this pattern
        tracking_desc = f"acceptance: {desc}"
        track_id = LearningStore.add_blind_spot(conn, tracking_desc)
        learning.blind_spots.append({"id": track_id, "description": tracking_desc})
        tracking_count += 1

        # Threshold reached → promote to confirmed blind spot
        if tracking_count >= BLIND_SPOT_THRESHOLD:
            confirmed_desc = (
                f"{desc} — accepted {tracking_count}+ times; "
                f"pay EXTRA attention to this area"
            )
            confirmed_id = LearningStore.add_blind_spot(conn, confirmed_desc)
            learning.blind_spots.append({"id": confirmed_id, "description": confirmed_desc})

    learning.session_acceptances = []


async def synthesize_editorial_profile(conn, llm_client, model_id: str) -> str | None:
    """Synthesize an editorial profile from accumulated learning data.

    Loads all learning entries from *conn*, assembles the synthesis prompt,
    calls the LLM, validates the result, and saves via
    ``LearningStore.save_editorial_profile()`` on success.

    Returns the profile text if successful, or ``None`` if the minimum entry
    threshold is not met, the LLM call fails, or the result contains a
    forbidden phrase (anti-sycophancy guard).
    """
    data = LearningStore.load(conn)

    preferences = data.get("preferences", [])
    blind_spots = data.get("blind_spots", [])
    resolutions = data.get("resolutions", [])
    ambiguity_intentional = data.get("ambiguity_intentional", [])
    ambiguity_accidental = data.get("ambiguity_accidental", [])
    review_count = data.get("review_count", 0)

    # Only count substantive entries — exclude "acceptance:" tracking entries
    visible_blind_spots = [
        b for b in blind_spots
        if not b.get("description", "").startswith("acceptance:")
    ]
    entry_count = (
        len(preferences)
        + len(visible_blind_spots)
        + len(resolutions)
        + len(ambiguity_intentional)
        + len(ambiguity_accidental)
    )
    if entry_count < PROFILE_MIN_ENTRIES:
        return None

    def _fmt(entries, use_confidence: bool = False) -> str:
        if not entries:
            return "[none]"
        lines = []
        for e in entries:
            desc = e.get("description", str(e))
            if use_confidence:
                conf = float(e.get("confidence", 0.5))
                lines.append(f"- [confidence: {conf:.1f}] {desc}")
            else:
                lines.append(f"- {desc}")
        return "\n".join(lines)

    prompt = (
        "You are analyzing an author's editorial learning data to generate a concise profile\n"
        "of their writing and reviewing style.\n\n"
        "INPUT: All recorded learning data for this project.\n\n"
        f"PREFERENCES (things the author consistently rejects as non-issues):\n{_fmt(preferences, use_confidence=True)}\n\n"
        f"BLIND SPOTS (things the author consistently accepts as problems):\n{_fmt(visible_blind_spots)}\n\n"
        f"RESOLUTIONS (how the author typically addresses issues):\n{_fmt(resolutions)}\n\n"
        "AMBIGUITY PATTERNS:\n"
        f"  Intentional: {_fmt(ambiguity_intentional)}\n"
        f"  Accidental: {_fmt(ambiguity_accidental)}\n\n"
        f"REVIEW COUNT: {review_count}\n\n"
        "TASK:\n"
        "Write a concise editorial profile (150-250 words) of this author for use as context\n"
        "by an AI editorial critic. The profile should:\n\n"
        "1. Describe the author's prose style and genre tendencies as inferred from their\n"
        "   preferences and resolutions.\n"
        "2. State clearly which editorial categories they treat as flexible vs. non-negotiable.\n"
        "3. Flag any confirmed blind spots explicitly — areas where the author accepts problems\n"
        "   consistently but may not be fixing them. Phrase these as directives: \"Pay extra\n"
        "   attention to X.\"\n"
        "4. Note any unusual or deliberate stylistic patterns that an editorial critic might\n"
        "   otherwise flag as errors.\n\n"
        "DO NOT:\n"
        "- Flatter the author or describe their choices as \"masterful\" or \"sophisticated.\"\n"
        "- Soften confirmed blind spots — they must be stated directly.\n"
        "- Invent characteristics not supported by the learning data.\n"
        "- Use bullet points. Write in prose.\n"
        "- Reference CANON.md or world-building rules — those are always enforced regardless of preferences.\n\n"
        "Output only the profile text. No preamble, no explanation."
    )

    try:
        op_start("synthesize_profile", "learning")
        response = await llm_client.create_message(
            model=model_id,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        profile_text = response.text.strip()
    except Exception:
        op_complete("synthesize_profile", "learning", status="failed")
        logger.warning("Editorial profile synthesis failed — LLM call error", exc_info=True)
        return None

    # Anti-sycophancy guard: discard profiles containing forbidden phrases
    profile_lower = profile_text.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in profile_lower:
            op_complete("synthesize_profile", "learning", status="failed")
            logger.warning(
                "Editorial profile discarded: contains forbidden phrase %r", phrase
            )
            return None

    LearningStore.save_editorial_profile(conn, profile_text)
    op_complete("synthesize_profile", "learning", status="ok")
    return profile_text


def generate_learning_markdown(learning: LearningData) -> str:
    """Generate LEARNING.md content from learning data."""
    lines = [
        "# Learning",
        "",
        f"PROJECT: {learning.project_name}",
        f"LAST_UPDATED: {datetime.now().strftime('%Y-%m-%d')}",
        f"REVIEW_COUNT: {learning.review_count}",
        "",
    ]

    if learning.editorial_profile:
        lines.extend([
            "## Editorial Profile",
            "",
            learning.editorial_profile,
            "",
            "---",
            "",
        ])

    lines.extend([
        "## Preferences",
        "",
    ])

    if learning.preferences:
        for pref in learning.preferences:
            confidence = float(pref.get("confidence", 0.5))
            lines.append(f"- [confidence: {confidence:.1f}] {pref.get('description', pref)}")
    else:
        lines.append("[none yet]")

    lines.extend(["", "## Blind Spots", ""])
    # Exclude "acceptance:" tracking entries — those are housekeeping, not user-visible content
    visible_blind_spots = [
        bs for bs in learning.blind_spots
        if not bs.get("description", "").startswith("acceptance:")
    ]
    if visible_blind_spots:
        for bs in visible_blind_spots:
            lines.append(f"- {bs.get('description', bs)}")
    else:
        lines.append("[none yet]")

    lines.extend(["", "## Resolutions", ""])
    if learning.resolutions:
        for res in learning.resolutions:
            lines.append(f"- {res.get('description', res)}")
    else:
        lines.append("[none yet]")

    lines.extend(["", "## Ambiguity Patterns", "", "### Intentional", ""])
    if learning.ambiguity_intentional:
        for amb in learning.ambiguity_intentional:
            lines.append(f"- {amb.get('description', amb)}")
    else:
        lines.append("[none yet]")

    lines.extend(["", "### Accidental", ""])
    if learning.ambiguity_accidental:
        for amb in learning.ambiguity_accidental:
            lines.append(f"- {amb.get('description', amb)}")
    else:
        lines.append("[none yet]")

    return "\n".join(lines)


def export_learning_markdown(project_path: Path) -> Path:
    """Export learning data from database to LEARNING.md."""
    conn = get_connection(project_path)
    try:
        markdown = LearningStore.export_markdown(conn)
    finally:
        conn.close()

    filepath = project_path / "LEARNING.md"
    filepath.write_text(markdown, encoding="utf-8")
    return filepath


def reset_learning(project_path: Path) -> None:
    """Reset persisted learning data for a project."""
    conn = get_connection(project_path)
    try:
        LearningStore.reset(conn)
    finally:
        conn.close()
