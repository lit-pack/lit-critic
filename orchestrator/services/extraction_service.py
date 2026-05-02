"""Knowledge extraction workflow service."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from core.log_utils import op_start, op_complete
from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.knowledge_override_store import KnowledgeOverrideStore
from orchestrator.runtime.llm import LLMClient
from orchestrator.runtime.prompts import get_knowledge_extraction_prompt
from orchestrator.services.scene_projection_service import compute_file_hash


# Extraction calls need more headroom than generic analysis — complex scenes produce
# large JSON responses.  Use a minimum floor and a ceiling for retry escalation.
_EXTRACTION_MIN_TOKENS = 8192
_EXTRACTION_TOKEN_CEILING = 16_384


async def extract_scene_knowledge(
    scene_content: str,
    scene_filename: str,
    canon_text: str,
    existing_knowledge: Any,
    client: LLMClient,
    model: str,
    max_tokens: int,
    conn: sqlite3.Connection,
    content_hash: str | None = None,
) -> dict:
    """Extract structured knowledge for one scene and persist it.

    *content_hash* should be the bytes-hash of the scene file on disk
    (from ``compute_file_hash``) so the stored ``content_hash`` matches
    what ``scene_status_service`` compares against.  When omitted, a
    UTF-8 text hash of ``scene_content`` is used as a fallback — this is
    only safe when the content hasn't been decoded through UTF-8 in a
    way that differs from the on-disk bytes (e.g. BOM stripping).
    """
    prompt = get_knowledge_extraction_prompt(
        scene_content,
        canon_text,
        _stringify_existing_knowledge(existing_knowledge),
    )

    # Use a higher token floor for extraction — JSON responses can be large.
    current_max = max(max_tokens, _EXTRACTION_MIN_TOKENS)

    for attempt in range(2):
        response = await client.create_message(
            model=model,
            max_tokens=current_max,
            messages=[{"role": "user", "content": prompt}],
        )
        if not response.truncated:
            break
        next_max = min(current_max * 2, _EXTRACTION_TOKEN_CEILING)
        if attempt == 0 and next_max > current_max:
            logger.warning(
                "Knowledge extraction truncated for %r at %d tokens, retrying with %d",
                scene_filename, current_max, next_max,
            )
            current_max = next_max
        else:
            raise ValueError(
                f"Knowledge extraction truncated after retry with {current_max} tokens. "
                "The scene may be too complex for a single extraction call."
            )

    payload = _parse_extraction_payload(response.text)
    _persist_scene_payload(
        conn=conn,
        scene_filename=scene_filename,
        scene_content=scene_content,
        payload=payload,
        content_hash=content_hash,
    )
    return payload


def aggregate_threads(conn: sqlite3.Connection) -> list[dict]:
    """Rebuild aggregated thread rows from per-scene thread events."""
    events = ExtractionStore.load_thread_events(conn)
    existing = {row["thread_id"]: row for row in ExtractionStore.load_all_threads(conn)}

    grouped: dict[str, list[dict]] = {}
    for row in events:
        grouped.setdefault(str(row["thread_id"]), []).append(row)

    conn.execute("DELETE FROM extracted_threads")
    conn.commit()

    for thread_id, thread_events in grouped.items():
        ordered = sorted(thread_events, key=lambda row: str(row.get("scene_filename") or ""))
        opened_events = [row for row in ordered if row.get("event_type") == "opened"]
        closed_events = [row for row in ordered if row.get("event_type") == "closed"]

        opened_in = (
            str(opened_events[0].get("scene_filename"))
            if opened_events
            else str(ordered[0].get("scene_filename"))
        )
        last_advanced = str(ordered[-1].get("scene_filename"))
        resolved_in = (
            str(closed_events[-1].get("scene_filename")) if closed_events else None
        )
        status = "resolved" if closed_events else "active"

        question = existing.get(thread_id, {}).get("question")
        notes = next(
            (str(row.get("notes")) for row in reversed(ordered) if row.get("notes")),
            existing.get(thread_id, {}).get("notes"),
        )

        ExtractionStore.upsert_thread(
            conn,
            thread_id=thread_id,
            question=question,
            status=status,
            opened_in=opened_in,
            last_advanced=last_advanced,
            resolved_in=resolved_in,
            notes=notes,
        )

    return ExtractionStore.load_all_threads(conn)


async def extract_stale_scenes(
    project_path: Path,
    conn: sqlite3.Connection,
    client: LLMClient,
    model: str,
    max_tokens: int,
    scene_keys: list[str],
) -> dict:
    """Extract knowledge for the given *scene_keys*.

    *scene_keys* must be a list of project-root-relative scene paths that the
    caller has already determined need extraction (e.g. via
    ``scene_status_service.list_scene_statuses``).  This function does **not**
    re-check staleness — that is the sole responsibility of the caller.

    Skips:
    - Files that do not exist on disk (logged as a warning).
    - Files whose ``extraction_locked`` flag is set in the DB.
    """
    project_root = Path(project_path)
    canon_path = project_root / "CANON.md"
    canon_text = canon_path.read_text(encoding="utf-8") if canon_path.exists() else ""

    extracted: list[str] = []
    skipped_locked: list[str] = []
    failed: list[dict] = []

    existing_knowledge_summary = _build_existing_knowledge_summary(conn)

    for scene_filename in scene_keys:
        scene_file = project_root / scene_filename
        if not scene_file.exists():
            logger.warning(
                "extract_stale_scenes: scene file not found on disk — %r", scene_filename
            )
            continue

        current_hash = compute_file_hash(scene_file)
        metadata = ExtractionStore.load_scene_metadata(conn, scene_filename)

        if metadata and int(metadata.get("extraction_locked") or 0) == 1:
            skipped_locked.append(scene_filename)
            continue

        scene_content = scene_file.read_text(encoding="utf-8")
        try:
            op_start("extract_knowledge", scene_filename)
            payload = await extract_scene_knowledge(
                scene_content=scene_content,
                scene_filename=scene_filename,
                canon_text=canon_text,
                existing_knowledge=existing_knowledge_summary,
                client=client,
                model=model,
                max_tokens=max_tokens,
                conn=conn,
                content_hash=current_hash,
            )
            extracted.append(scene_filename)
            op_complete(
                "extract_knowledge",
                scene_filename,
                characters=len(payload.get("characters") or []),
                terms=len(payload.get("terms") or []),
            )
            existing_knowledge_summary = _build_existing_knowledge_summary(conn)
        except Exception as exc:  # noqa: BLE001 - report and continue
            op_complete("extract_knowledge", scene_filename, status="failed")
            logger.warning("Scene extraction failed for %r: %s", scene_filename, exc)
            _mark_scene_failed(conn, scene_filename, current_hash)
            failed.append({"scene_filename": scene_filename, "error": str(exc)})

    aggregate_threads(conn)
    return {
        "scenes_scanned": len(scene_keys),
        "extracted": extracted,
        "skipped_locked": skipped_locked,
        "failed": failed,
    }


def reconcile_knowledge(conn: sqlite3.Connection, llm_output: str) -> dict:
    """Parse and apply LLM reconciliation output to the extracted knowledge tables.

    For ``updates``: applies field-level corrections for unlocked entities.
    For ``removals``: deletes entities with no author overrides; flags those
    with overrides for human review instead of deleting silently.

    Returns::

        {
            "applied_updates": int,
            "applied_removals": int,
            "flagged_for_review": list[{"category": ..., "entity_key": ..., "reason": ...}],
        }
    """
    data = _parse_llm_json_response(llm_output)
    if data is None:
        logger.warning("reconcile_knowledge: invalid JSON from LLM — skipping reconciliation")
        return {"applied_updates": 0, "applied_removals": 0, "flagged_for_review": []}

    updates = data.get("updates") or []
    removals = data.get("removals") or []
    applied_updates = 0
    applied_removals = 0
    flagged_for_review: list[dict] = []

    for update in updates:
        if not isinstance(update, dict):
            continue
        category = _as_str_or_none(update.get("category"))
        entity_key = _as_str_or_none(update.get("entity_key"))
        field = _as_str_or_none(update.get("field"))
        new_value = update.get("new_value")

        if not category or not entity_key or not field:
            continue
        if category not in ExtractionStore._ENTITY_TABLE_MAP:
            logger.debug("reconcile_knowledge: unknown category %r — skipping", category)
            continue

        if ExtractionStore.is_entity_locked(conn, category, entity_key):
            logger.debug("reconcile_knowledge: skipping locked entity update %s/%s", category, entity_key)
            continue

        try:
            _apply_entity_field_update(conn, category, entity_key, field, new_value)
            applied_updates += 1
        except Exception as exc:
            logger.warning(
                "reconcile_knowledge: failed to apply update %s/%s.%s: %s",
                category, entity_key, field, exc,
            )

    for removal in removals:
        if not isinstance(removal, dict):
            continue
        category = _as_str_or_none(removal.get("category"))
        entity_key = _as_str_or_none(removal.get("entity_key"))
        reason = _as_str_or_none(removal.get("reason")) or "no longer supported by scene text"

        if not category or not entity_key:
            continue
        if category not in ExtractionStore._ENTITY_TABLE_MAP:
            continue

        # Safety net: skip locked entities
        if ExtractionStore.is_entity_locked(conn, category, entity_key):
            logger.debug("reconcile_knowledge: skipping locked entity removal %s/%s", category, entity_key)
            continue

        # If the entity has author overrides, flag for review instead of silently deleting
        overrides = KnowledgeOverrideStore.load_overrides_for_entity(conn, category, entity_key)
        if overrides:
            flagged_for_review.append({
                "category": category,
                "entity_key": entity_key,
                "reason": reason,
            })
            continue

        try:
            deleted = _delete_entity_by_category(conn, category, entity_key)
            if deleted:
                applied_removals += 1
        except Exception as exc:
            logger.warning(
                "reconcile_knowledge: failed to delete %s/%s: %s",
                category, entity_key, exc,
            )

    return {
        "applied_updates": applied_updates,
        "applied_removals": applied_removals,
        "flagged_for_review": flagged_for_review,
    }


def cleanup_orphaned_entities(conn: sqlite3.Connection) -> dict:
    """Remove characters and terms no longer sourced from any scene.

    This is a deterministic, source-table–driven cleanup that runs after scene
    extraction.  Because ``_persist_scene_payload`` deletes old source rows for
    each re-extracted scene before inserting new ones, any character or term
    that has zero remaining source rows is definitively absent from all scene
    text and should be removed from the knowledge DB.

    Rules (same as reconcile_knowledge):
    - Locked entities are left untouched.
    - Entities with author overrides are flagged for review instead of deleted.

    Threads are intentionally excluded: ``aggregate_threads()`` already deletes
    all thread rows and rebuilds from events, so threads with no events are
    cleaned up automatically as part of the extraction flow.

    Returns::

        {
            "removed": [{"category": ..., "entity_key": ...}, ...],
            "flagged_for_review": [{"category": ..., "entity_key": ..., "reason": ...}, ...],
        }
    """
    removed: list[dict] = []
    flagged_for_review: list[dict] = []

    orphan_checks = [
        ("characters", ExtractionStore.find_orphaned_characters(conn)),
        ("terms", ExtractionStore.find_orphaned_terms(conn)),
    ]

    for category, orphan_keys in orphan_checks:
        for entity_key in orphan_keys:
            # Skip locked entities — the lock explicitly says "don't touch this".
            if ExtractionStore.is_entity_locked(conn, category, entity_key):
                logger.debug(
                    "cleanup_orphaned_entities: preserving locked orphan %s/%s",
                    category,
                    entity_key,
                )
                continue

            # If the entity has author overrides, flag for human review instead
            # of deleting silently (same policy as reconcile_knowledge).
            overrides = KnowledgeOverrideStore.load_overrides_for_entity(conn, category, entity_key)
            if overrides:
                flagged_for_review.append({
                    "category": category,
                    "entity_key": entity_key,
                    "reason": (
                        f"{category[:-1]} no longer appears in any scene — "
                        "has author overrides, please review"
                    ),
                })
                logger.info(
                    "cleanup_orphaned_entities: flagged for review (has overrides) %s/%s",
                    category,
                    entity_key,
                )
                continue

            try:
                deleted = _delete_entity_by_category(conn, category, entity_key)
                if deleted:
                    removed.append({"category": category, "entity_key": entity_key})
                    logger.info(
                        "cleanup_orphaned_entities: removed orphaned %s/%s",
                        category,
                        entity_key,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "cleanup_orphaned_entities: failed to delete %s/%s: %s",
                    category,
                    entity_key,
                    exc,
                )

    return {"removed": removed, "flagged_for_review": flagged_for_review}


# Primary-key fields for each entity category.  These are the stable DB keys and
# must never be updated via the reconciliation path — doing so creates a duplicate
# row instead of renaming the original.
_PK_FIELDS: dict[str, str] = {
    "characters": "name",
    "terms": "term",
    "threads": "thread_id",
    "timeline": "scene_filename",
}


def _apply_entity_field_update(
    conn: sqlite3.Connection,
    category: str,
    entity_key: str,
    field: str,
    new_value: Any,
) -> None:
    """Apply a single field update to an entity via its upsert method."""
    pk_field = _PK_FIELDS.get(category)
    if pk_field and field == pk_field:
        logger.debug(
            "_apply_entity_field_update: refusing PK-field update %s/%s.%s → ignoring",
            category, entity_key, field,
        )
        return

    str_value = _as_str_or_none(new_value)

    if category == "characters":
        existing = _load_entity_dict(ExtractionStore.load_all_characters(conn), "name", entity_key)
        if existing is None:
            return
        updated = {**existing, field: str_value}
        ExtractionStore.upsert_character(
            conn,
            name=updated.get("name", entity_key),
            aka=updated.get("aka"),
            category=updated.get("category"),
            traits=updated.get("traits"),
            relationships=updated.get("relationships"),
            first_seen=updated.get("first_seen"),
        )

    elif category == "terms":
        existing = _load_entity_dict(ExtractionStore.load_all_terms(conn), "term", entity_key)
        if existing is None:
            return
        updated = {**existing, field: str_value}
        ExtractionStore.upsert_term(
            conn,
            term=updated.get("term", entity_key),
            category=updated.get("category"),
            definition=updated.get("definition"),
            translation=updated.get("translation"),
            notes=updated.get("notes"),
            first_seen=updated.get("first_seen"),
        )

    elif category == "threads":
        existing = _load_entity_dict(ExtractionStore.load_all_threads(conn), "thread_id", entity_key)
        if existing is None:
            return
        updated = {**existing, field: str_value}
        ExtractionStore.upsert_thread(
            conn,
            thread_id=updated.get("thread_id", entity_key),
            question=updated.get("question"),
            status=updated.get("status"),
            opened_in=updated.get("opened_in"),
            last_advanced=updated.get("last_advanced"),
            resolved_in=updated.get("resolved_in"),
            notes=updated.get("notes"),
        )

    elif category == "timeline":
        existing = _load_entity_dict(ExtractionStore.load_all_timeline(conn), "scene_filename", entity_key)
        if existing is None:
            return
        updated = {**existing, field: str_value}
        ExtractionStore.upsert_timeline(
            conn,
            scene_filename=updated.get("scene_filename", entity_key),
            summary=updated.get("summary") or "",
            chrono_hint=updated.get("chrono_hint"),
        )


def _delete_entity_by_category(conn: sqlite3.Connection, category: str, entity_key: str) -> bool:
    """Delete an entity by category and key. Returns True if deleted."""
    if category == "characters":
        return ExtractionStore.delete_character(conn, entity_key)
    if category == "terms":
        return ExtractionStore.delete_term(conn, entity_key)
    if category == "threads":
        return ExtractionStore.delete_thread(conn, entity_key)
    if category == "timeline":
        return ExtractionStore.delete_timeline_entry(conn, entity_key)
    return False


def _load_entity_dict(rows: list[dict], key_field: str, key_value: str) -> dict | None:
    """Find one entity dict by its key field value."""
    return next((r for r in rows if r.get(key_field) == key_value), None)


def _persist_scene_payload(
    conn: sqlite3.Connection,
    scene_filename: str,
    scene_content: str,
    payload: dict,
    content_hash: str | None = None,
) -> None:
    """Persist extracted payload components into extracted knowledge tables.

    *content_hash* is the canonical scene hash (bytes-hash from
    ``compute_file_hash``).  It must match what ``scene_status_service``
    compares against so the scene becomes non-stale after extraction.
    When omitted, a UTF-8 text hash of ``scene_content`` is used as a
    fallback (see note in ``extract_scene_knowledge``).
    """
    scene_metadata = payload.get("scene_metadata") or {}
    characters = payload.get("characters") or []
    terms = payload.get("terms") or []
    thread_events = payload.get("thread_events") or []
    timeline = payload.get("timeline") or {}

    resolved_content_hash = (
        content_hash if content_hash is not None else _hash_text(scene_content)
    )

    ExtractionStore.upsert_scene_metadata(
        conn,
        scene_filename=scene_filename,
        content_hash=resolved_content_hash,
        location=_as_str_or_none(scene_metadata.get("location")),
        pov=_as_str_or_none(scene_metadata.get("pov")),
        tense=_as_str_or_none(scene_metadata.get("tense")),
        tense_notes=_as_str_or_none(scene_metadata.get("tense_notes")),
        cast_present=_as_list(scene_metadata.get("cast_present")),
        objective=_as_str_or_none(scene_metadata.get("objective")),
        cont_anchors=_as_jsonish(scene_metadata.get("cont_anchors")),
        extract_status="ok",
    )

    # Check timeline lock status before deleting the existing entry so that
    # a locked timeline row is not erased by the pre-extraction cleanup step.
    timeline_locked = ExtractionStore.is_entity_locked(conn, "timeline", scene_filename)

    conn.execute(
        "DELETE FROM extracted_thread_events WHERE scene_filename = ?",
        (scene_filename,),
    )
    conn.execute(
        "DELETE FROM extracted_character_sources WHERE scene_filename = ?",
        (scene_filename,),
    )
    conn.execute(
        "DELETE FROM extracted_term_sources WHERE scene_filename = ?",
        (scene_filename,),
    )
    if not timeline_locked:
        conn.execute(
            "DELETE FROM extracted_timeline WHERE scene_filename = ?",
            (scene_filename,),
        )
    conn.commit()

    for item in characters:
        if not isinstance(item, dict):
            continue
        name = _as_str_or_none(item.get("name"))
        if not name:
            continue
        if ExtractionStore.is_entity_locked(conn, "characters", name):
            logger.debug("Skipping locked character: %r", name)
            continue
        ExtractionStore.upsert_character(
            conn,
            name=name,
            aka=_as_jsonish(item.get("aka")),
            category=_as_str_or_none(item.get("category")),
            traits=_as_jsonish(item.get("traits")),
            relationships=_as_jsonish(item.get("relationships")),
            first_seen=scene_filename,
        )
        ExtractionStore.upsert_character_source(
            conn,
            name=name,
            scene_filename=scene_filename,
        )

    for item in terms:
        if not isinstance(item, dict):
            continue
        term = _as_str_or_none(item.get("term"))
        if not term:
            continue
        if ExtractionStore.is_entity_locked(conn, "terms", term):
            logger.debug("Skipping locked term: %r", term)
            continue
        ExtractionStore.upsert_term(
            conn,
            term=term,
            category=_as_str_or_none(item.get("category")),
            definition=_as_str_or_none(item.get("definition")),
            translation=_as_str_or_none(item.get("translation")),
            notes=_as_str_or_none(item.get("notes")),
            first_seen=scene_filename,
        )
        ExtractionStore.upsert_term_source(
            conn,
            term=term,
            scene_filename=scene_filename,
        )

    for item in thread_events:
        if not isinstance(item, dict):
            continue
        thread_id = _as_str_or_none(item.get("thread_id"))
        if not thread_id:
            continue
        event_type = _as_str_or_none(item.get("event_type")) or "advanced"
        if event_type not in {"opened", "advanced", "closed"}:
            event_type = "advanced"

        question = _as_str_or_none(item.get("question"))
        notes = _as_str_or_none(item.get("notes"))
        if question or notes:
            if ExtractionStore.is_entity_locked(conn, "threads", thread_id):
                logger.debug("Skipping locked thread: %r", thread_id)
            else:
                ExtractionStore.upsert_thread(
                    conn,
                    thread_id=thread_id,
                    question=question,
                    notes=notes,
                )

        ExtractionStore.upsert_thread_event(
            conn,
            thread_id=thread_id,
            scene_filename=scene_filename,
            event_type=event_type,
            notes=notes,
        )

    if isinstance(timeline, dict):
        summary = _as_str_or_none(timeline.get("summary"))
        chrono_hint = _as_str_or_none(timeline.get("chrono_hint"))
        if summary or chrono_hint:
            if timeline_locked:
                logger.debug("Skipping locked timeline entry for scene: %r", scene_filename)
            else:
                ExtractionStore.upsert_timeline(
                    conn,
                    scene_filename=scene_filename,
                    summary=summary or "",
                    chrono_hint=chrono_hint,
                )


def _parse_llm_json_response(text: str) -> dict | None:
    """Parse an LLM response into a JSON dict, tolerating markdown fences and preamble.

    Returns ``None`` if no valid JSON object can be extracted.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass

    return None


def _parse_extraction_payload(text: str) -> dict:
    """Parse LLM JSON response into extraction payload dict."""
    data = _parse_llm_json_response(text)
    if data is None:
        if text:
            logger.warning(
                "Knowledge extraction parse failure. len=%d head=%s tail=%s",
                len(text),
                repr(text[:200]),
                repr(text[-200:]),
            )
        else:
            logger.warning("Knowledge extraction parse failure. Raw response: <empty>")
        raise ValueError("Knowledge extraction response is not valid JSON")

    data.setdefault("scene_metadata", {})
    data.setdefault("characters", [])
    data.setdefault("terms", [])
    data.setdefault("thread_events", [])
    data.setdefault("timeline", {})
    return data


def _mark_scene_failed(conn: sqlite3.Connection, scene_filename: str, content_hash: str) -> None:
    """Persist failed extraction state for one scene."""
    existing = ExtractionStore.load_scene_metadata(conn, scene_filename) or {}
    ExtractionStore.upsert_scene_metadata(
        conn,
        scene_filename=scene_filename,
        content_hash=content_hash,
        extracted_at=existing.get("extracted_at"),
        location=existing.get("location"),
        pov=existing.get("pov"),
        tense=existing.get("tense"),
        tense_notes=existing.get("tense_notes"),
        cast_present=existing.get("cast_present"),
        objective=existing.get("objective"),
        cont_anchors=existing.get("cont_anchors"),
        extract_status="failed",
        extraction_locked=int(existing.get("extraction_locked") or 0),
        locked_at=existing.get("locked_at"),
    )


def _apply_overrides_with_annotations(
    conn: sqlite3.Connection,
    category: str,
    raw_entities: list[dict],
    entity_key_field: str,
) -> list[dict]:
    """Apply stored overrides onto entities and annotate overridden fields.

    For each entity, fields with stored overrides are updated to the override
    value.  The original extracted value is preserved as ``original_<field>``,
    and the list of overridden fields is added as ``user_curated_fields``.
    Entities with no overrides are returned unchanged (no extra keys added).
    """
    override_rows = KnowledgeOverrideStore.load_all_overrides(conn, category)
    by_entity: dict[str, dict[str, str]] = {}
    for row in override_rows:
        by_entity.setdefault(row["entity_key"], {})[row["field_name"]] = row["override_value"]

    result: list[dict] = []
    for entity in raw_entities:
        entity_key = str(entity.get(entity_key_field, ""))
        overrides = by_entity.get(entity_key)
        if not overrides:
            result.append(dict(entity))
            continue
        updated = dict(entity)
        curated: list[str] = []
        for field_name, override_value in overrides.items():
            original = updated.get(field_name)
            if original != override_value:
                updated[f"original_{field_name}"] = original
                updated[field_name] = override_value
                curated.append(field_name)
        if curated:
            updated["user_curated_fields"] = sorted(curated)
        result.append(updated)
    return result


def _build_existing_knowledge_summary(conn: sqlite3.Connection) -> str:
    """Return compact JSON summary of extracted knowledge with overrides applied.

    Each entity that has author overrides will have:
    - Its field(s) set to the override value (canonical form).
    - Companion ``original_<field>`` keys with the raw extracted value (text anchor).
    - A ``user_curated_fields`` list naming which fields were overridden.

    This gives the extraction LLM both the canonical name and the original
    text fragment so it can recognise existing entities without creating duplicates.
    """
    snapshot = {
        "characters": _apply_overrides_with_annotations(
            conn, "characters", ExtractionStore.load_all_characters(conn), "name"
        ),
        "terms": _apply_overrides_with_annotations(
            conn, "terms", ExtractionStore.load_all_terms(conn), "term"
        ),
        "threads": ExtractionStore.load_all_threads(conn),
        "timeline": ExtractionStore.load_all_timeline(conn),
    }
    return json.dumps(snapshot, ensure_ascii=False)


def _stringify_existing_knowledge(existing_knowledge: Any) -> str:
    """Normalize existing knowledge payload into prompt-safe text."""
    if isinstance(existing_knowledge, str):
        return existing_knowledge
    try:
        return json.dumps(existing_knowledge, ensure_ascii=False)
    except TypeError:
        return str(existing_knowledge)


def _hash_text(text: str) -> str:
    """Compute stable short hash compatible with scene projection hashing."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _as_str_or_none(value: Any) -> str | None:
    """Normalize JSON scalar values into optional strings."""
    if value is None:
        return None
    return str(value)


def _as_list(value: Any) -> list:
    """Normalize unknown JSON field into list form."""
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _as_jsonish(value: Any) -> Any:
    """Normalize unknown JSON-ish values for store serializers."""
    if value is None:
        return None
    if isinstance(value, (dict, list, str)):
        return value
    return str(value)


__all__ = [
    "aggregate_threads",
    "extract_scene_knowledge",
    "extract_stale_scenes",
]
