"""Serialization helpers for extracted knowledge prompt context."""

from __future__ import annotations

import sqlite3

from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.knowledge_override_store import KnowledgeOverrideStore


def serialize_characters(conn: sqlite3.Connection) -> str:
    """Serialize extracted characters (with overrides) into markdown."""
    rows = ExtractionStore.load_all_characters(conn)
    merged = KnowledgeOverrideStore.apply_overrides(conn, "characters", rows, "name")
    if not merged:
        return "## Characters\n\n[none]"

    lines = ["## Characters", ""]
    for row in merged:
        lines.append(f"### {row.get('name', '')}".rstrip())
        lines.append(f"- Category: {_fmt(row.get('category'))}")
        lines.append(f"- AKA: {_fmt_list(row.get('aka'))}")
        lines.append(f"- Traits: {_fmt(row.get('traits'))}")
        lines.append(f"- Relationships: {_fmt(row.get('relationships'))}")
        lines.append(f"- First seen: {_fmt(row.get('first_seen'))}")
        lines.append("")
    return "\n".join(lines).rstrip()


def serialize_terms(conn: sqlite3.Connection) -> str:
    """Serialize extracted terms (with overrides) into markdown."""
    rows = ExtractionStore.load_all_terms(conn)
    merged = KnowledgeOverrideStore.apply_overrides(conn, "terms", rows, "term")
    if not merged:
        return "## Terms\n\n[none]"

    lines = ["## Terms", ""]
    for row in merged:
        lines.append(f"### {row.get('term', '')}".rstrip())
        lines.append(f"- Category: {_fmt(row.get('category'))}")
        lines.append(f"- Definition: {_fmt(row.get('definition'))}")
        lines.append(f"- Translation: {_fmt(row.get('translation'))}")
        lines.append(f"- Notes: {_fmt(row.get('notes'))}")
        lines.append(f"- First seen: {_fmt(row.get('first_seen'))}")
        lines.append("")
    return "\n".join(lines).rstrip()


def serialize_threads(conn: sqlite3.Connection) -> str:
    """Serialize extracted thread aggregates (with overrides) into markdown."""
    rows = ExtractionStore.load_all_threads(conn)
    merged = KnowledgeOverrideStore.apply_overrides(conn, "threads", rows, "thread_id")
    if not merged:
        return "## Threads\n\n[none]"

    lines = ["## Threads", ""]
    for row in merged:
        lines.append(f"### {row.get('thread_id', '')}".rstrip())
        lines.append(f"- Question: {_fmt(row.get('question'))}")
        lines.append(f"- Status: {_fmt(row.get('status'))}")
        lines.append(f"- Opened in: {_fmt(row.get('opened_in'))}")
        lines.append(f"- Last advanced: {_fmt(row.get('last_advanced'))}")
        lines.append(f"- Resolved in: {_fmt(row.get('resolved_in'))}")
        lines.append(f"- Notes: {_fmt(row.get('notes'))}")
        lines.append("")
    return "\n".join(lines).rstrip()


def serialize_timeline(conn: sqlite3.Connection) -> str:
    """Serialize extracted timeline rows (with overrides) into markdown."""
    rows = ExtractionStore.load_all_timeline(conn)
    merged = KnowledgeOverrideStore.apply_overrides(
        conn,
        "timeline",
        rows,
        "scene_filename",
    )
    if not merged:
        return "## Timeline\n\n[none]"

    lines = ["## Timeline", ""]
    for row in merged:
        lines.append(f"### {row.get('scene_filename', '')}".rstrip())
        lines.append(f"- Summary: {_fmt(row.get('summary'))}")
        lines.append(f"- Chrono hint: {_fmt(row.get('chrono_hint'))}")
        lines.append("")
    return "\n".join(lines).rstrip()


def serialize_all_knowledge(conn: sqlite3.Connection) -> dict[str, str]:
    """Serialize all extracted knowledge categories keyed by index-slot names."""
    return {
        "cast": serialize_characters(conn),
        "glossary": serialize_terms(conn),
        "threads": serialize_threads(conn),
        "timeline": serialize_timeline(conn),
    }


def _fmt(value) -> str:
    if value is None or value == "":
        return "[none]"
    return str(value)


def _fmt_list(value) -> str:
    if not value:
        return "[none]"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


__all__ = [
    "serialize_all_knowledge",
    "serialize_characters",
    "serialize_terms",
    "serialize_threads",
    "serialize_timeline",
]
