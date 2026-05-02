"""Tests for the ``orchestrator.runtime.db`` SQLite storage layer."""

import pytest
from orchestrator.runtime.db import LearningStore, CATEGORY_PREFERENCE, CATEGORY_BLIND_SPOT
from orchestrator.runtime.models import LearningData


class TestLearningStore:
    """Tests for LearningStore CRUD operations."""

    def test_ensure_exists_creates(self, db_conn):
        lid = LearningStore.ensure_exists(db_conn, "My Novel")
        assert isinstance(lid, int)
        # Calling again returns same id
        lid2 = LearningStore.ensure_exists(db_conn)
        assert lid == lid2

    def test_load_empty(self, db_conn):
        data = LearningStore.load(db_conn)
        assert data["id"] is None
        assert data["preferences"] == []

    def test_save_and_load(self, db_conn):
        ld = LearningData(project_name="Test", review_count=5)
        ld.preferences.append({"description": "Pref 1"})
        ld.blind_spots.append({"description": "Blind 1"})
        LearningStore.save_from_learning_data(db_conn, ld)

        data = LearningStore.load(db_conn)
        assert data["project_name"] == "Test"
        assert data["review_count"] == 5
        assert len(data["preferences"]) == 1
        assert len(data["blind_spots"]) == 1

    def test_add_entry(self, db_conn):
        eid = LearningStore.add_entry(db_conn, CATEGORY_PREFERENCE, "Test pref")
        assert isinstance(eid, int)
        entries = LearningStore.list_entries(db_conn, CATEGORY_PREFERENCE)
        assert len(entries) == 1
        assert entries[0]["description"] == "Test pref"

    def test_remove_entry(self, db_conn):
        eid = LearningStore.add_entry(db_conn, CATEGORY_PREFERENCE, "Test")
        assert LearningStore.remove_entry(db_conn, eid) is True
        assert LearningStore.list_entries(db_conn, CATEGORY_PREFERENCE) == []

    def test_increment_review_count(self, db_conn):
        LearningStore.ensure_exists(db_conn)
        LearningStore.increment_review_count(db_conn)
        LearningStore.increment_review_count(db_conn)
        data = LearningStore.load(db_conn)
        assert data["review_count"] == 2

    def test_reset(self, db_conn):
        ld = LearningData(project_name="Test", review_count=3)
        ld.preferences.append({"description": "Pref"})
        LearningStore.save_from_learning_data(db_conn, ld)

        LearningStore.reset(db_conn)
        data = LearningStore.load(db_conn)
        assert data["id"] is None

    def test_export_markdown(self, db_conn):
        ld = LearningData(project_name="Novel", review_count=2)
        ld.preferences.append({"description": "[prose] Test preference"})
        LearningStore.save_from_learning_data(db_conn, ld)

        md = LearningStore.export_markdown(db_conn)
        assert "# Learning" in md
        assert "PROJECT: Novel" in md
        assert "REVIEW_COUNT: 2" in md
        assert "[prose] Test preference" in md  # confidence prefix prepended by export

    def test_export_markdown_includes_confidence_prefix(self, db_conn):
        """Exported markdown should include [confidence: X.X] prefix for preferences."""
        LearningStore.add_preference(db_conn, "[prose] Sentence fragments OK", confidence=0.7)
        LearningStore.add_preference(db_conn, "[logic] Motivation implicit", confidence=0.5)

        md = LearningStore.export_markdown(db_conn)
        assert "[confidence: 0.7]" in md
        assert "[confidence: 0.5]" in md

    def test_confidence_column_exists_and_defaults_to_half(self, db_conn):
        """New learning entries should have confidence = 0.5 by default."""
        eid = LearningStore.add_preference(db_conn, "Test preference")
        entries = LearningStore.list_entries(db_conn, CATEGORY_PREFERENCE)
        assert len(entries) == 1
        assert entries[0]["confidence"] == pytest.approx(0.5)

    def test_update_confidence(self, db_conn):
        """update_confidence() should update the stored value."""
        eid = LearningStore.add_preference(db_conn, "Test", confidence=0.5)
        LearningStore.update_confidence(db_conn, eid, 0.7)
        entries = LearningStore.list_entries(db_conn, CATEGORY_PREFERENCE)
        assert entries[0]["confidence"] == pytest.approx(0.7)
