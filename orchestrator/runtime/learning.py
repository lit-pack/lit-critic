"""
Learning layer for the lit-critic system.

Uses SQLite via ``server.db`` as the source of truth for all learning data.
``LEARNING.md`` is generated on demand as an export (human-readable, version-controllable).

Public API
----------
Loading:
    load_learning(project_path) → LearningData
    load_learning_from_db(conn) → LearningData

Persisting:
    persist_learning(learning, project_path)

Session processing:
    update_learning_from_session(learning)

Export:
    export_learning_markdown(project_path) → Path
    generate_learning_markdown(learning) → str
"""

from datetime import datetime
from pathlib import Path

from .db import get_connection, LearningStore
from .models import LearningData

# ---------------------------------------------------------------------------
# Immediate DB commit (hot path)
# ---------------------------------------------------------------------------


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
    learning.session_ambiguity_answers = []  # drained

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


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_learning(project_path: Path) -> LearningData:
    """Load learning data from the project's SQLite database.

    Falls back to parsing ``LEARNING.md`` if the database has no learning
    data yet (one-time migration on first use).
    """
    conn = get_connection(project_path)
    try:
        data = LearningStore.load(conn)

        # If DB has data, use it
        if data.get("id") is not None:
            return _dict_to_learning_data(data)

        # No data in DB yet — try to import from LEARNING.md
        learning = _load_learning_from_markdown(project_path)
        if learning.project_name != "Unknown" or learning.review_count > 0 or learning.preferences:
            # Found existing LEARNING.md data — import it to DB
            LearningStore.save_from_learning_data(conn, learning)

        return learning
    finally:
        conn.close()


def load_learning_from_db(conn) -> LearningData:
    """Load learning data from an already-open DB connection."""
    data = LearningStore.load(conn)
    return _dict_to_learning_data(data)


def _dict_to_learning_data(data: dict) -> LearningData:
    """Convert a LearningStore.load() dict to a LearningData object."""
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
            "description": entry.get("description", str(entry))
        })
    for entry in data.get("ambiguity_intentional", []):
        learning.ambiguity_intentional.append({
            "id": entry.get("id"),
            "description": entry.get("description", str(entry))
        })
    for entry in data.get("ambiguity_accidental", []):
        learning.ambiguity_accidental.append({
            "id": entry.get("id"),
            "description": entry.get("description", str(entry))
        })
    return learning


def _load_learning_from_markdown(project_path: Path) -> LearningData:
    """Parse existing LEARNING.md (legacy format) for one-time import."""
    learning = LearningData()
    filepath = project_path / "LEARNING.md"

    if not filepath.exists():
        return learning

    content = filepath.read_text(encoding='utf-8')

    current_section = None
    current_subsection = None

    for line in content.split('\n'):
        line = line.strip()

        if line.startswith('PROJECT:'):
            learning.project_name = line.split(':', 1)[1].strip()
        elif line.startswith('REVIEW_COUNT:'):
            try:
                learning.review_count = int(line.split(':', 1)[1].strip())
            except ValueError:
                pass
        elif line == '## Preferences':
            current_section = 'preferences'
        elif line == '## Blind Spots':
            current_section = 'blind_spots'
        elif line == '## Resolutions':
            current_section = 'resolutions'
        elif line == '## Ambiguity Patterns':
            current_section = 'ambiguity'
        elif line == '### Intentional':
            current_subsection = 'intentional'
        elif line == '### Accidental':
            current_subsection = 'accidental'
        elif line.startswith('- ') and current_section:
            entry = {"description": line[2:]}
            if current_section == 'preferences':
                learning.preferences.append(entry)
            elif current_section == 'blind_spots':
                learning.blind_spots.append(entry)
            elif current_section == 'resolutions':
                learning.resolutions.append(entry)
            elif current_section == 'ambiguity':
                if current_subsection == 'intentional':
                    learning.ambiguity_intentional.append(entry)
                elif current_subsection == 'accidental':
                    learning.ambiguity_accidental.append(entry)

    return learning


# ---------------------------------------------------------------------------
# Persisting
# ---------------------------------------------------------------------------


def persist_learning(learning: LearningData, project_path: Path) -> None:
    """Save learning data to the project's SQLite database.

    Call this after ``update_learning_from_session()`` to persist the
    updated learning data.
    """
    conn = get_connection(project_path)
    try:
        LearningStore.save_from_learning_data(conn, learning)
    finally:
        conn.close()


def persist_learning_with_conn(learning: LearningData, conn) -> None:
    """Save learning data using an already-open DB connection."""
    LearningStore.save_from_learning_data(conn, learning)


# ---------------------------------------------------------------------------
# Session processing
# ---------------------------------------------------------------------------


def update_learning_from_session(learning: LearningData) -> None:
    """Process session data into learning entries.

    Phase 4 enhancement: Uses explicit preference rules extracted during discussion
    when available, falling back to the original format when not.
    """

    # Process rejections -> preferences
    for rejection in learning.session_rejections:
        # Prefer explicit preference rule from discussion (Phase 4: richer learning)
        if rejection.get('preference_rule'):
            desc = f"[{rejection['lens']}] {rejection['preference_rule']}"
        else:
            reason = rejection.get('reason', 'no reason given')
            desc = f"[{rejection['lens']}] {rejection['pattern']} — Author says: \"{reason}\""
        # Check if similar preference already exists
        if not any(desc in p.get('description', '') for p in learning.preferences):
            learning.preferences.append({"description": desc})

    # Process acceptances -> potential blind spots (need multiple occurrences)
    for acceptance in learning.session_acceptances:
        desc = f"[{acceptance['lens']}] {acceptance['pattern']}"
        existing = [bs for bs in learning.blind_spots if acceptance['pattern'] in bs.get('description', '')]
        if not existing:
            pass

    # Process ambiguity answers
    for answer in learning.session_ambiguity_answers:
        desc = f"{answer['location']}: {answer['description']}"
        if answer['intentional']:
            if not any(desc in a.get('description', '') for a in learning.ambiguity_intentional):
                learning.ambiguity_intentional.append({"description": desc})
        else:
            if not any(desc in a.get('description', '') for a in learning.ambiguity_accidental):
                learning.ambiguity_accidental.append({"description": desc})

    # Clear session lists so subsequent calls are idempotent
    learning.session_rejections = []
    learning.session_acceptances = []
    learning.session_ambiguity_answers = []
    # NOTE: review_count is NOT incremented here; use LearningStore.increment_review_count()
    # at session completion (once per session, not once per export).


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def generate_learning_markdown(learning: LearningData) -> str:
    """Generate LEARNING.md content from learning data."""
    lines = [
        "# Learning",
        "",
        f"PROJECT: {learning.project_name}",
        f"LAST_UPDATED: {datetime.now().strftime('%Y-%m-%d')}",
        f"REVIEW_COUNT: {learning.review_count}",
        "",
        "## Preferences",
        "",
    ]

    if learning.preferences:
        for pref in learning.preferences:
            confidence = float(pref.get("confidence", 0.5))
            lines.append(f"- [confidence: {confidence:.1f}] {pref.get('description', pref)}")
    else:
        lines.append("[none yet]")

    lines.extend([
        "",
        "## Blind Spots",
        "",
    ])

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

    lines.extend([
        "",
        "## Resolutions",
        "",
    ])

    if learning.resolutions:
        for res in learning.resolutions:
            lines.append(f"- {res.get('description', res)}")
    else:
        lines.append("[none yet]")

    lines.extend([
        "",
        "## Ambiguity Patterns",
        "",
        "### Intentional",
        "",
    ])

    if learning.ambiguity_intentional:
        for amb in learning.ambiguity_intentional:
            lines.append(f"- {amb.get('description', amb)}")
    else:
        lines.append("[none yet]")

    lines.extend([
        "",
        "### Accidental",
        "",
    ])

    if learning.ambiguity_accidental:
        for amb in learning.ambiguity_accidental:
            lines.append(f"- {amb.get('description', amb)}")
    else:
        lines.append("[none yet]")

    return '\n'.join(lines)


def export_learning_markdown(project_path: Path) -> Path:
    """Export learning data from the database to LEARNING.md.

    Returns the path to the written file.
    """
    conn = get_connection(project_path)
    try:
        markdown = LearningStore.export_markdown(conn)
    finally:
        conn.close()

    filepath = project_path / "LEARNING.md"
    filepath.write_text(markdown, encoding='utf-8')
    return filepath


def save_learning_to_file(learning: LearningData, project_path: Path) -> Path:
    """Save learning data to both the database and LEARNING.md.

    This is a convenience function that:
    1. Processes session data via ``update_learning_from_session()``
    2. Persists to SQLite
    3. Exports to LEARNING.md

    Returns the path to the LEARNING.md file.
    """
    update_learning_from_session(learning)
    persist_learning(learning, project_path)

    markdown = generate_learning_markdown(learning)
    filepath = project_path / "LEARNING.md"
    filepath.write_text(markdown, encoding='utf-8')
    return filepath
