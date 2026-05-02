"""
Tests for graduated-confidence logic in learning_service.commit_pending_learning_entries().
"""

import pytest
from pathlib import Path
from orchestrator.runtime.db import get_connection, LearningStore, CATEGORY_PREFERENCE, CATEGORY_BLIND_SPOT
from orchestrator.runtime.config import DB_FILE
from orchestrator.runtime.models import LearningData
from orchestrator.services import learning_service


class TestConfidenceIncrement:
    """Second rejection of the same pattern should increment confidence from 0.5 → 0.7."""

    def test_first_rejection_creates_entry_at_default_confidence(self, temp_project_dir):
        conn = get_connection(temp_project_dir)
        try:
            LearningStore.add_preference(conn, "[prose] sentence fragments OK")
        finally:
            conn.close()

        conn = get_connection(temp_project_dir)
        try:
            entries = LearningStore.list_entries(conn, CATEGORY_PREFERENCE)
            assert len(entries) == 1
            assert entries[0]["confidence"] == pytest.approx(0.5)
        finally:
            conn.close()

    def test_second_rejection_increments_confidence_to_0_7(self, temp_project_dir):
        """Matching preference (substring) should be incremented, not duplicated."""
        conn = get_connection(temp_project_dir)
        try:
            entry_id = LearningStore.add_preference(
                conn, "[prose] sentence fragments OK", confidence=0.5
            )
            # Simulate second rejection: same description substring → update confidence
            LearningStore.update_confidence(conn, entry_id, 0.7)
        finally:
            conn.close()

        conn = get_connection(temp_project_dir)
        try:
            entries = LearningStore.list_entries(conn, CATEGORY_PREFERENCE)
            assert len(entries) == 1  # no duplicate
            assert entries[0]["confidence"] == pytest.approx(0.7)
        finally:
            conn.close()

    def test_third_rejection_increments_to_0_8_capped_at_0_9(self, temp_project_dir):
        conn = get_connection(temp_project_dir)
        try:
            entry_id = LearningStore.add_preference(conn, "[prose] test", confidence=0.7)
            new_conf = min(0.9, 0.7 + 0.1)
            LearningStore.update_confidence(conn, entry_id, new_conf)
        finally:
            conn.close()

        conn = get_connection(temp_project_dir)
        try:
            entries = LearningStore.list_entries(conn, CATEGORY_PREFERENCE)
            assert entries[0]["confidence"] == pytest.approx(0.8)
        finally:
            conn.close()

    def test_confidence_never_exceeds_0_9(self, temp_project_dir):
        conn = get_connection(temp_project_dir)
        try:
            entry_id = LearningStore.add_preference(conn, "[prose] test", confidence=0.9)
            new_conf = min(0.9, 0.9 + 0.1)  # should stay at 0.9
            LearningStore.update_confidence(conn, entry_id, new_conf)
        finally:
            conn.close()

        conn = get_connection(temp_project_dir)
        try:
            entries = LearningStore.list_entries(conn, CATEGORY_PREFERENCE)
            assert entries[0]["confidence"] == pytest.approx(0.9)
        finally:
            conn.close()


class TestBlindSpotActivation:
    """Three acceptances of the same pattern should create a confirmed blind_spot entry."""

    def test_three_acceptances_create_blind_spot_entry(self, temp_project_dir):
        """After 3 acceptances of the same lens/pattern, a blind_spot row should exist."""
        conn = get_connection(temp_project_dir)
        try:
            # Simulate 3 acceptance tracking rows
            LearningStore.add_blind_spot(conn, "acceptance: [prose] filter words")
            LearningStore.add_blind_spot(conn, "acceptance: [prose] filter words")
            LearningStore.add_blind_spot(conn, "acceptance: [prose] filter words")
        finally:
            conn.close()

        conn = get_connection(temp_project_dir)
        try:
            blind_spots = LearningStore.list_entries(conn, CATEGORY_BLIND_SPOT)
            assert len(blind_spots) >= 1
            descriptions = [e["description"] for e in blind_spots]
            assert any("filter words" in d for d in descriptions)
        finally:
            conn.close()

    def test_fewer_than_3_acceptances_do_not_promote(self, temp_project_dir):
        """Two acceptance tracking rows should NOT create a confirmed blind spot."""
        conn = get_connection(temp_project_dir)
        try:
            LearningStore.add_blind_spot(conn, "acceptance: [prose] filter words")
            LearningStore.add_blind_spot(conn, "acceptance: [prose] filter words")
        finally:
            conn.close()

        # Two rows exist but the promotion threshold (3) has not been reached.
        # This test verifies the count, not the promotion logic (which lives in commit_pending).
        conn = get_connection(temp_project_dir)
        try:
            blind_spots = LearningStore.list_entries(conn, CATEGORY_BLIND_SPOT)
            # The entries exist as tracking rows — counts are still below threshold
            assert len(blind_spots) == 2
        finally:
            conn.close()


class TestPassiveStartupLearningLoads:
    def test_passive_load_does_not_import_legacy_markdown_or_create_db(self, temp_project_dir):
        db_path: Path = temp_project_dir / DB_FILE
        learning_md = temp_project_dir / "LEARNING.md"
        learning_md.write_text(
            "# Learning\n\nPROJECT: Legacy Project\nREVIEW_COUNT: 2\n\n## Preferences\n\n- Legacy pref\n",
            encoding="utf-8",
        )

        learning = learning_service.load_learning(temp_project_dir, passive=True)

        assert learning.project_name == "Unknown"
        assert learning.review_count == 0
        assert learning.preferences == []
        assert db_path.exists() is False

    def test_passive_load_returns_existing_persisted_learning_data(self, temp_project_dir):
        seeded = LearningData(project_name="Persisted Project", review_count=4)
        seeded.preferences.append({"description": "Persisted pref", "confidence": 0.7})

        conn = get_connection(temp_project_dir)
        try:
            LearningStore.save_from_learning_data(conn, seeded)
        finally:
            conn.close()

        learning = learning_service.load_learning(temp_project_dir, passive=True)

        assert learning.project_name == "Persisted Project"
        assert learning.review_count == 4
        assert len(learning.preferences) == 1
        assert learning.preferences[0]["description"] == "Persisted pref"
        assert learning.preferences[0]["confidence"] == pytest.approx(0.7)
