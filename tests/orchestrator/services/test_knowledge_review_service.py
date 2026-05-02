import sqlite3

from orchestrator.persistence.database import init_db
from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.services.knowledge_review_service import (
    delete_override,
    export_knowledge_markdown,
    get_knowledge_review,
    submit_override,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_get_knowledge_review_merges_overrides_for_category():
    conn = _conn()
    try:
        ExtractionStore.upsert_character(
            conn,
            name="Amelia",
            category="supporting",
            first_seen="scene-01.txt",
        )
        submit_override(
            conn,
            category="cast",
            entity_key="Amelia",
            field_name="category",
            value="main",
        )

        review = get_knowledge_review(conn, "characters")

        assert review["category"] == "characters"
        assert review["entity_key_field"] == "name"
        assert review["entities"][0]["category"] == "main"
        assert review["overrides"][0]["field_name"] == "category"
    finally:
        conn.close()


def test_submit_and_delete_override_roundtrip():
    conn = _conn()
    try:
        submit_override(
            conn,
            category="terms",
            entity_key="Aether",
            field_name="definition",
            value="Refined definition",
        )

        with_override = get_knowledge_review(conn, "glossary")
        assert len(with_override["overrides"]) == 1

        removed = delete_override(
            conn,
            category="term",
            entity_key="Aether",
            field_name="definition",
        )
        assert removed is True
        assert (
            delete_override(
                conn,
                category="term",
                entity_key="Aether",
                field_name="definition",
            )
            is False
        )

        after_delete = get_knowledge_review(conn, "terms")
        assert after_delete["overrides"] == []
    finally:
        conn.close()


def test_export_knowledge_markdown_contains_all_sections():
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Basil", category="ally")
        markdown = export_knowledge_markdown(conn)

        assert "# Knowledge Export" in markdown
        assert "## Characters" in markdown
        assert "## Terms" in markdown
        assert "## Threads" in markdown
        assert "## Timeline" in markdown
    finally:
        conn.close()
