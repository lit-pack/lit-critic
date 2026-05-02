"""Integration tests: flag and staleness persistence round-trip through the service layer.

Tests verify the full flow:
  1. save flags → get_knowledge_review shows flagged=True
  2. dismiss flag → get_knowledge_review shows flagged=False
  3. save staleness cache → get_knowledge_review shows stale=True
  4. clear staleness cache → get_knowledge_review shows stale=False
"""

import sqlite3

import pytest

from orchestrator.persistence.database import init_db
from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.knowledge_state_store import KnowledgeStateStore
from orchestrator.services.knowledge_review_service import (
    dismiss_review_flag,
    get_knowledge_review,
)


@pytest.fixture
def conn():
    """In-memory SQLite with full schema, seeded with one character entity."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    # Insert a character so get_knowledge_review has something to enrich
    c.execute(
        """INSERT INTO extracted_characters (name, last_updated)
           VALUES ('Aria', '2025-01-01T00:00:00')"""
    )
    c.commit()
    yield c
    c.close()


def _get_entity(conn: sqlite3.Connection, category: str, entity_key: str) -> dict | None:
    """Helper: load the named entity from get_knowledge_review result."""
    review = get_knowledge_review(conn, category)
    for entity in review["entities"]:
        if entity.get("entity_key") == entity_key:
            return entity
    return None


# ---------------------------------------------------------------------------
# Flag persistence round-trips
# ---------------------------------------------------------------------------


class TestFlagRoundTrip:
    def test_save_flags_then_review_shows_flagged(self, conn):
        KnowledgeStateStore.save_review_flags(
            conn,
            [{"category": "characters", "entity_key": "Aria", "reason": "conflict"}],
        )
        entity = _get_entity(conn, "characters", "Aria")
        assert entity is not None
        assert entity["flagged"] is True
        assert entity["flagged_reason"] == "conflict"

    def test_no_flags_shows_not_flagged(self, conn):
        entity = _get_entity(conn, "characters", "Aria")
        assert entity is not None
        assert entity["flagged"] is False
        assert entity["flagged_reason"] == ""

    def test_dismiss_flag_shows_not_flagged(self, conn):
        KnowledgeStateStore.save_review_flags(
            conn,
            [{"category": "characters", "entity_key": "Aria", "reason": "conflict"}],
        )
        # Confirm it's flagged first
        entity_before = _get_entity(conn, "characters", "Aria")
        assert entity_before["flagged"] is True

        # Dismiss via service function
        dismiss_review_flag(conn, "characters", "Aria")

        entity_after = _get_entity(conn, "characters", "Aria")
        assert entity_after["flagged"] is False
        assert entity_after["flagged_reason"] == ""

    def test_dismiss_nonexistent_flag_is_noop(self, conn):
        """Dismissing a flag that was never set should not raise."""
        dismiss_review_flag(conn, "characters", "Ghost")
        entity = _get_entity(conn, "characters", "Aria")
        assert entity["flagged"] is False


# ---------------------------------------------------------------------------
# Staleness persistence round-trips
# ---------------------------------------------------------------------------


class TestStalenessRoundTrip:
    def test_save_stale_entity_shows_stale(self, conn):
        KnowledgeStateStore.save_staleness_cache(
            conn,
            [{"category": "characters", "entity_key": "Aria"}],
            all_stale=False,
        )
        entity = _get_entity(conn, "characters", "Aria")
        assert entity is not None
        assert entity["stale"] is True

    def test_no_staleness_cache_shows_not_stale(self, conn):
        entity = _get_entity(conn, "characters", "Aria")
        assert entity is not None
        assert entity["stale"] is False

    def test_all_stale_sentinel_marks_every_entity_stale(self, conn):
        KnowledgeStateStore.save_staleness_cache(conn, [], all_stale=True)
        entity = _get_entity(conn, "characters", "Aria")
        assert entity is not None
        assert entity["stale"] is True

    def test_clear_staleness_cache_shows_not_stale(self, conn):
        KnowledgeStateStore.save_staleness_cache(
            conn,
            [{"category": "characters", "entity_key": "Aria"}],
            all_stale=False,
        )
        KnowledgeStateStore.clear_staleness_cache(conn)
        entity = _get_entity(conn, "characters", "Aria")
        assert entity["stale"] is False

    def test_clear_all_stale_sentinel_shows_not_stale(self, conn):
        KnowledgeStateStore.save_staleness_cache(conn, [], all_stale=True)
        KnowledgeStateStore.clear_staleness_cache(conn)
        entity = _get_entity(conn, "characters", "Aria")
        assert entity["stale"] is False


# ---------------------------------------------------------------------------
# Combined flag + stale fields are independent
# ---------------------------------------------------------------------------


class TestFlagAndStaleAreIndependent:
    def test_flagged_not_stale(self, conn):
        KnowledgeStateStore.save_review_flags(
            conn, [{"category": "characters", "entity_key": "Aria"}]
        )
        entity = _get_entity(conn, "characters", "Aria")
        assert entity["flagged"] is True
        assert entity["stale"] is False

    def test_stale_not_flagged(self, conn):
        KnowledgeStateStore.save_staleness_cache(
            conn, [{"category": "characters", "entity_key": "Aria"}], all_stale=False
        )
        entity = _get_entity(conn, "characters", "Aria")
        assert entity["flagged"] is False
        assert entity["stale"] is True

    def test_both_flagged_and_stale(self, conn):
        KnowledgeStateStore.save_review_flags(
            conn, [{"category": "characters", "entity_key": "Aria", "reason": "orphan"}]
        )
        KnowledgeStateStore.save_staleness_cache(
            conn, [{"category": "characters", "entity_key": "Aria"}], all_stale=False
        )
        entity = _get_entity(conn, "characters", "Aria")
        assert entity["flagged"] is True
        assert entity["stale"] is True
