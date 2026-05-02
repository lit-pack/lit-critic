"""Knowledge review helpers for extracted entities and author overrides."""

from __future__ import annotations

import sqlite3

from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.knowledge_override_store import KnowledgeOverrideStore
from orchestrator.persistence.knowledge_state_store import KnowledgeStateStore
from orchestrator.services.knowledge_serializer import (
    serialize_characters,
    serialize_terms,
    serialize_threads,
    serialize_timeline,
)

_CATEGORY_ALIAS = {
    "characters": "characters",
    "character": "characters",
    "cast": "characters",
    "terms": "terms",
    "term": "terms",
    "glossary": "terms",
    "threads": "threads",
    "thread": "threads",
    "timeline": "timeline",
    "scene_metadata": "scene_metadata",
    "scene-metadata": "scene_metadata",
}

_CATEGORY_ENTITY_KEY = {
    "characters": "name",
    "terms": "term",
    "threads": "thread_id",
    "timeline": "scene_filename",
    "scene_metadata": "scene_filename",
}


_LOCKABLE_ENTITY_CATEGORIES = frozenset({"characters", "terms", "threads", "timeline"})


def get_knowledge_review(conn: sqlite3.Connection, category: str) -> dict:
    """Return extracted entities and overrides for one review category."""
    normalized = _normalize_category(category)
    entity_key_field = _CATEGORY_ENTITY_KEY[normalized]

    raw_items = _load_entities(conn, normalized)
    merged_items = KnowledgeOverrideStore.apply_overrides(
        conn,
        normalized,
        raw_items,
        entity_key_field,
    )
    # Inject the stable original DB key into each merged entity.  apply_overrides
    # may have mutated the primary-key field (e.g. "name" for characters) with an
    # override value, which causes the frontend to derive a wrong entityKey and then
    # silently fail on delete (DELETE WHERE name = <overridden_value> → 0 rows).
    for raw, merged in zip(raw_items, merged_items):
        merged["entity_key"] = str(raw.get(entity_key_field, ""))

    # Inject entity_locked (boolean) for the four lockable entity categories.
    # Reads authoritative lock status from the DB so it is never influenced by overrides.
    if normalized in _LOCKABLE_ENTITY_CATEGORIES:
        lock_status = ExtractionStore.get_entity_lock_status(conn, normalized)
        for raw, merged in zip(raw_items, merged_items):
            key = str(raw.get(entity_key_field, ""))
            merged["entity_locked"] = lock_status.get(key, False)

    overrides = KnowledgeOverrideStore.load_all_overrides(conn, normalized)

    # Enrich each entity with persisted flagged/stale state from DB.
    flag_rows = KnowledgeStateStore.load_review_flags(conn)
    flag_index = {(r["category"], r["entity_key"]): r for r in flag_rows}
    stale_data = KnowledgeStateStore.load_staleness_cache(conn)
    all_stale = stale_data["all_stale"]
    stale_index = {(e["category"], e["entity_key"]) for e in stale_data["entities"]}

    for raw, merged in zip(raw_items, merged_items):
        ek = str(raw.get(entity_key_field, ""))
        flag_row = flag_index.get((normalized, ek))
        merged["flagged"] = flag_row is not None
        merged["flagged_reason"] = flag_row["reason"] if flag_row else ""
        merged["stale"] = all_stale or (normalized, ek) in stale_index

    return {
        "category": normalized,
        "entity_key_field": entity_key_field,
        "entities": merged_items,
        "raw_entities": raw_items,
        "overrides": overrides,
    }


def submit_override(
    conn: sqlite3.Connection,
    category: str,
    entity_key: str,
    field_name: str,
    value: str,
) -> None:
    """Persist an author override for one extracted field."""
    normalized = _normalize_category(category)
    KnowledgeOverrideStore.upsert_override(
        conn,
        category=normalized,
        entity_key=entity_key,
        field_name=field_name,
        value=value,
    )


def delete_override(
    conn: sqlite3.Connection,
    category: str,
    entity_key: str,
    field_name: str,
) -> bool:
    """Delete a previously saved author override."""
    normalized = _normalize_category(category)
    return KnowledgeOverrideStore.delete_override(
        conn,
        category=normalized,
        entity_key=entity_key,
        field_name=field_name,
    )


def delete_entity(
    conn: sqlite3.Connection,
    category: str,
    entity_key: str,
) -> bool:
    """Delete an extracted entity and all its overrides, then mark scenes stale.

    Returns True if the entity existed and was removed, False if it was not found.
    """
    normalized = _normalize_category(category)

    # Dispatch to the correct store delete method.
    if normalized == "characters":
        existed = ExtractionStore.delete_character(conn, entity_key)
    elif normalized == "terms":
        existed = ExtractionStore.delete_term(conn, entity_key)
    elif normalized == "threads":
        existed = ExtractionStore.delete_thread(conn, entity_key)
    elif normalized in ("timeline", "scene_metadata"):
        existed = ExtractionStore.delete_timeline_entry(conn, entity_key)
    else:
        existed = False

    if not existed:
        return False

    # Cascade-remove all author overrides for this entity.
    KnowledgeOverrideStore.delete_all_overrides_for_entity(conn, normalized, entity_key)

    # Mark scenes stale so the next Refresh Knowledge re-extracts.
    if normalized in ("timeline", "scene_metadata"):
        ExtractionStore.mark_scene_stale(conn, entity_key)
    else:
        for row in ExtractionStore.load_all_scene_metadata(conn):
            ExtractionStore.mark_scene_stale(conn, row["scene_filename"])

    # Remove any persisted flag or staleness entry for this entity.
    KnowledgeStateStore.delete_review_flag(conn, normalized, entity_key)
    KnowledgeStateStore.delete_staleness_entry(conn, normalized, entity_key)

    return True


def dismiss_review_flag(
    conn: sqlite3.Connection,
    category: str,
    entity_key: str,
) -> None:
    """Remove the persisted review flag for one entity (dismiss without deleting)."""
    normalized = _normalize_category(category)
    KnowledgeStateStore.delete_review_flag(conn, normalized, entity_key)


def export_knowledge_markdown(conn: sqlite3.Connection) -> str:
    """Export extracted knowledge (with overrides) as markdown text."""
    sections = [
        "# Knowledge Export",
        "",
        serialize_characters(conn),
        "",
        serialize_terms(conn),
        "",
        serialize_threads(conn),
        "",
        serialize_timeline(conn),
    ]
    return "\n".join(sections).rstrip()


def _normalize_category(category: str) -> str:
    """Map user-facing category aliases to canonical override categories."""
    key = str(category).strip().lower()
    normalized = _CATEGORY_ALIAS.get(key)
    if normalized is None:
        valid = ", ".join(sorted(_CATEGORY_ENTITY_KEY))
        raise ValueError(f"Unknown knowledge category '{category}'. Valid categories: {valid}")
    return normalized


def _load_entities(conn: sqlite3.Connection, category: str) -> list[dict]:
    """Load raw extracted entities for one normalized review category."""
    if category == "characters":
        return ExtractionStore.load_all_characters(conn)
    if category == "terms":
        return ExtractionStore.load_all_terms(conn)
    if category == "threads":
        return ExtractionStore.load_all_threads(conn)
    if category == "timeline":
        return ExtractionStore.load_all_timeline(conn)
    return ExtractionStore.load_all_scene_metadata(conn)


__all__ = [
    "delete_entity",
    "delete_override",
    "dismiss_review_flag",
    "export_knowledge_markdown",
    "get_knowledge_review",
    "submit_override",
]
