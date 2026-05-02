import sqlite3

from orchestrator.persistence.database import init_db
from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.knowledge_override_store import KnowledgeOverrideStore
from orchestrator.services.knowledge_serializer import (
    serialize_all_knowledge,
    serialize_characters,
    serialize_terms,
    serialize_threads,
    serialize_timeline,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_serialize_empty_db_outputs_none_sections():
    conn = _conn()
    try:
        assert serialize_characters(conn) == "## Characters\n\n[none]"
        assert serialize_terms(conn) == "## Terms\n\n[none]"
        assert serialize_threads(conn) == "## Threads\n\n[none]"
        assert serialize_timeline(conn) == "## Timeline\n\n[none]"

        all_sections = serialize_all_knowledge(conn)
        assert all_sections == {
            "cast": "## Characters\n\n[none]",
            "glossary": "## Terms\n\n[none]",
            "threads": "## Threads\n\n[none]",
            "timeline": "## Timeline\n\n[none]",
        }
    finally:
        conn.close()


def test_serialize_sections_include_data_and_apply_overrides():
    conn = _conn()
    try:
        ExtractionStore.upsert_character(
            conn,
            name="Amelia",
            aka=["Lia", "The Seer"],
            category="supporting",
            traits={"role": "observer"},
            relationships=[{"target": "Iris", "description": "mentor"}],
            first_seen="text/ch1.txt",
        )
        KnowledgeOverrideStore.upsert_override(
            conn,
            category="characters",
            entity_key="Amelia",
            field_name="category",
            value="main",
        )

        ExtractionStore.upsert_term(
            conn,
            term="Aether",
            category="term",
            definition="Subtle energy",
            translation="αιθήρ",
            notes="Capitalized",
            first_seen="text/ch1.txt",
        )
        KnowledgeOverrideStore.upsert_override(
            conn,
            category="terms",
            entity_key="Aether",
            field_name="definition",
            value="Refined definition",
        )

        ExtractionStore.upsert_thread(
            conn,
            thread_id="who_stole_the_key",
            question="Who stole the key?",
            status="active",
            opened_in="text/ch1.txt",
            last_advanced="text/ch2.txt",
            notes="Still unresolved",
        )
        KnowledgeOverrideStore.upsert_override(
            conn,
            category="threads",
            entity_key="who_stole_the_key",
            field_name="status",
            value="resolved",
        )

        ExtractionStore.upsert_timeline(
            conn,
            scene_filename="text/ch1.txt",
            summary="Original summary",
            chrono_hint="Day 1 evening",
        )
        KnowledgeOverrideStore.upsert_override(
            conn,
            category="timeline",
            entity_key="text/ch1.txt",
            field_name="summary",
            value="Overridden summary",
        )

        characters = serialize_characters(conn)
        assert "## Characters" in characters
        assert "### Amelia" in characters
        assert "- Category: main" in characters
        assert "- AKA: Lia, The Seer" in characters

        terms = serialize_terms(conn)
        assert "## Terms" in terms
        assert "### Aether" in terms
        assert "- Definition: Refined definition" in terms

        threads = serialize_threads(conn)
        assert "## Threads" in threads
        assert "### who_stole_the_key" in threads
        assert "- Status: resolved" in threads

        timeline = serialize_timeline(conn)
        assert "## Timeline" in timeline
        assert "### text/ch1.txt" in timeline
        assert "- Summary: Overridden summary" in timeline

        all_sections = serialize_all_knowledge(conn)
        assert set(all_sections) == {"cast", "glossary", "threads", "timeline"}
        assert "### Amelia" in all_sections["cast"]
        assert "### Aether" in all_sections["glossary"]
    finally:
        conn.close()
