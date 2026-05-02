"""Unit tests for KnowledgeStateStore CRUD operations."""

import sqlite3

import pytest

from orchestrator.persistence.database import init_db
from orchestrator.persistence.knowledge_state_store import KnowledgeStateStore


@pytest.fixture
def conn():
    """In-memory SQLite connection with full schema applied."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Review flags
# ---------------------------------------------------------------------------


class TestReviewFlags:
    def test_save_and_load(self, conn):
        flags = [
            {"category": "characters", "entity_key": "Aria", "reason": "conflict"},
            {"category": "terms", "entity_key": "Ether", "reason": ""},
        ]
        KnowledgeStateStore.save_review_flags(conn, flags)
        loaded = KnowledgeStateStore.load_review_flags(conn)
        assert len(loaded) == 2
        keys = {(r["category"], r["entity_key"]) for r in loaded}
        assert ("characters", "Aria") in keys
        assert ("terms", "Ether") in keys

    def test_save_upserts(self, conn):
        KnowledgeStateStore.save_review_flags(
            conn, [{"category": "characters", "entity_key": "Aria", "reason": "old"}]
        )
        KnowledgeStateStore.save_review_flags(
            conn, [{"category": "characters", "entity_key": "Aria", "reason": "new"}]
        )
        loaded = KnowledgeStateStore.load_review_flags(conn)
        assert len(loaded) == 1
        assert loaded[0]["reason"] == "new"

    def test_delete_single_flag(self, conn):
        KnowledgeStateStore.save_review_flags(
            conn,
            [
                {"category": "characters", "entity_key": "Aria"},
                {"category": "characters", "entity_key": "Bor"},
            ],
        )
        KnowledgeStateStore.delete_review_flag(conn, "characters", "Aria")
        loaded = KnowledgeStateStore.load_review_flags(conn)
        assert len(loaded) == 1
        assert loaded[0]["entity_key"] == "Bor"

    def test_delete_nonexistent_is_noop(self, conn):
        KnowledgeStateStore.delete_review_flag(conn, "characters", "Ghost")
        assert KnowledgeStateStore.load_review_flags(conn) == []

    def test_clear_review_flags(self, conn):
        KnowledgeStateStore.save_review_flags(
            conn, [{"category": "characters", "entity_key": "Aria"}]
        )
        KnowledgeStateStore.clear_review_flags(conn)
        assert KnowledgeStateStore.load_review_flags(conn) == []

    def test_load_empty(self, conn):
        assert KnowledgeStateStore.load_review_flags(conn) == []


# ---------------------------------------------------------------------------
# Staleness cache
# ---------------------------------------------------------------------------


class TestStalenessCache:
    def test_save_and_load_entities(self, conn):
        entities = [
            {"category": "characters", "entity_key": "Aria", "source_path": "ch1.md"},
            {"category": "terms", "entity_key": "Ether"},
        ]
        KnowledgeStateStore.save_staleness_cache(conn, entities, all_stale=False)
        result = KnowledgeStateStore.load_staleness_cache(conn)
        assert result["all_stale"] is False
        assert len(result["entities"]) == 2
        keys = {(e["category"], e["entity_key"]) for e in result["entities"]}
        assert ("characters", "Aria") in keys
        assert ("terms", "Ether") in keys

    def test_all_stale_sentinel(self, conn):
        KnowledgeStateStore.save_staleness_cache(conn, [], all_stale=True)
        result = KnowledgeStateStore.load_staleness_cache(conn)
        assert result["all_stale"] is True
        assert result["entities"] == []

    def test_save_replaces_existing(self, conn):
        KnowledgeStateStore.save_staleness_cache(
            conn,
            [{"category": "characters", "entity_key": "Aria"}],
            all_stale=False,
        )
        KnowledgeStateStore.save_staleness_cache(
            conn,
            [{"category": "terms", "entity_key": "Ether"}],
            all_stale=False,
        )
        result = KnowledgeStateStore.load_staleness_cache(conn)
        assert len(result["entities"]) == 1
        assert result["entities"][0]["entity_key"] == "Ether"

    def test_save_all_stale_clears_prior_entities(self, conn):
        KnowledgeStateStore.save_staleness_cache(
            conn,
            [{"category": "characters", "entity_key": "Aria"}],
            all_stale=False,
        )
        KnowledgeStateStore.save_staleness_cache(conn, [], all_stale=True)
        result = KnowledgeStateStore.load_staleness_cache(conn)
        assert result["all_stale"] is True
        assert result["entities"] == []

    def test_clear_staleness_cache(self, conn):
        KnowledgeStateStore.save_staleness_cache(conn, [], all_stale=True)
        KnowledgeStateStore.clear_staleness_cache(conn)
        result = KnowledgeStateStore.load_staleness_cache(conn)
        assert result["all_stale"] is False
        assert result["entities"] == []

    def test_delete_single_staleness_entry(self, conn):
        KnowledgeStateStore.save_staleness_cache(
            conn,
            [
                {"category": "characters", "entity_key": "Aria"},
                {"category": "characters", "entity_key": "Bor"},
            ],
            all_stale=False,
        )
        KnowledgeStateStore.delete_staleness_entry(conn, "characters", "Aria")
        result = KnowledgeStateStore.load_staleness_cache(conn)
        assert len(result["entities"]) == 1
        assert result["entities"][0]["entity_key"] == "Bor"

    def test_load_empty(self, conn):
        result = KnowledgeStateStore.load_staleness_cache(conn)
        assert result == {"all_stale": False, "entities": []}
