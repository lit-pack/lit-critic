import sqlite3

from orchestrator.persistence.database import init_db
from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.knowledge_override_store import KnowledgeOverrideStore


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_override_crud_and_loaders():
    conn = _conn()
    try:
        KnowledgeOverrideStore.upsert_override(
            conn,
            category="characters",
            entity_key="Amelia",
            field_name="category",
            value="main",
        )
        KnowledgeOverrideStore.upsert_override(
            conn,
            category="characters",
            entity_key="Amelia",
            field_name="notes",
            value="Primary POV",
        )
        KnowledgeOverrideStore.upsert_override(
            conn,
            category="terms",
            entity_key="Aether",
            field_name="definition",
            value="Refined definition",
        )

        entity_rows = KnowledgeOverrideStore.load_overrides_for_entity(
            conn,
            category="characters",
            entity_key="Amelia",
        )
        assert len(entity_rows) == 2
        assert {row["field_name"] for row in entity_rows} == {"category", "notes"}

        all_rows = KnowledgeOverrideStore.load_all_overrides(conn)
        assert len(all_rows) == 3

        char_rows = KnowledgeOverrideStore.load_all_overrides(conn, category="characters")
        assert len(char_rows) == 2
        assert all(row["category"] == "characters" for row in char_rows)

        KnowledgeOverrideStore.upsert_override(
            conn,
            category="characters",
            entity_key="Amelia",
            field_name="category",
            value="supporting",
        )
        updated = KnowledgeOverrideStore.load_overrides_for_entity(
            conn,
            category="characters",
            entity_key="Amelia",
        )
        by_field = {row["field_name"]: row["override_value"] for row in updated}
        assert by_field["category"] == "supporting"

        assert (
            KnowledgeOverrideStore.delete_override(
                conn,
                category="characters",
                entity_key="Amelia",
                field_name="notes",
            )
            is True
        )
        assert (
            KnowledgeOverrideStore.delete_override(
                conn,
                category="characters",
                entity_key="Amelia",
                field_name="notes",
            )
            is False
        )
    finally:
        conn.close()


def test_apply_overrides_and_override_survives_reextraction():
    conn = _conn()
    try:
        ExtractionStore.upsert_character(
            conn,
            name="Amelia",
            category="supporting",
            first_seen="text/ch1.txt",
        )
        ExtractionStore.upsert_character(
            conn,
            name="Iris",
            category="minor",
            first_seen="text/ch1.txt",
        )

        KnowledgeOverrideStore.upsert_override(
            conn,
            category="characters",
            entity_key="Amelia",
            field_name="category",
            value="main",
        )

        raw = ExtractionStore.load_all_characters(conn)
        merged = KnowledgeOverrideStore.apply_overrides(
            conn,
            category="characters",
            raw_entities=raw,
            entity_key_field="name",
        )
        by_name = {row["name"]: row for row in merged}
        assert by_name["Amelia"]["category"] == "main"
        assert by_name["Iris"]["category"] == "minor"

        ExtractionStore.upsert_character(
            conn,
            name="Amelia",
            category="supporting",
            first_seen="text/ch2.txt",
        )
        merged_after_reextract = KnowledgeOverrideStore.apply_overrides(
            conn,
            category="characters",
            raw_entities=ExtractionStore.load_all_characters(conn),
            entity_key_field="name",
        )
        by_name_after = {row["name"]: row for row in merged_after_reextract}
        assert by_name_after["Amelia"]["category"] == "main"
    finally:
        conn.close()
