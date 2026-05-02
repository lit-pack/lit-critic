import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.persistence.database import init_db
from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.knowledge_override_store import KnowledgeOverrideStore
from orchestrator.services import extraction_service
from orchestrator.services.extraction_service import (
    _apply_entity_field_update,
    _apply_overrides_with_annotations,
    _build_existing_knowledge_summary,
    reconcile_knowledge,
)
from orchestrator.services.scene_projection_service import compute_file_hash


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


class StubClient:
    def __init__(self, responses: list[str] | None = None, error: Exception | None = None):
        self._responses = list(responses or [])
        self._error = error
        self.calls: list[dict] = []

    async def create_message(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        text = self._responses.pop(0) if self._responses else "{}"
        return SimpleNamespace(text=text, truncated=False)


@pytest.mark.asyncio
async def test_extract_scene_knowledge_persists_payload():
    conn = _conn()
    try:
        payload = {
            "scene_metadata": {
                "location": "Sanctuary",
                "pov": "Amelia",
                "tense": "Past",
                "tense_notes": "Flashback on page 3",
                "cast_present": ["Amelia", "Iris"],
                "objective": "Find the key",
                "cont_anchors": {"mood": "tense"},
            },
            "characters": [
                {
                    "name": "Amelia",
                    "aka": ["Lia"],
                    "category": "main",
                    "traits": {"role": "protagonist"},
                    "relationships": [{"target": "Iris", "description": "mentor"}],
                }
            ],
            "terms": [
                {
                    "term": "Aether",
                    "category": "term",
                    "definition": "Subtle energy",
                    "translation": "αιθήρ",
                    "notes": "Capitalized",
                }
            ],
            "thread_events": [
                {
                    "thread_id": "who_stole_the_key",
                    "event_type": "opened",
                    "question": "Who stole the key?",
                    "notes": "Introduced in scene",
                }
            ],
            "timeline": {
                "summary": "Amelia notices the key is missing",
                "chrono_hint": "Day 1 evening",
            },
        }
        client = StubClient(responses=[json.dumps(payload)])

        result = await extraction_service.extract_scene_knowledge(
            scene_content="Scene body",
            scene_filename="text/ch1.txt",
            canon_text="canon",
            existing_knowledge={},
            client=client,
            model="test-model",
            max_tokens=500,
            conn=conn,
        )

        assert result["scene_metadata"]["location"] == "Sanctuary"
        metadata = ExtractionStore.load_scene_metadata(conn, "text/ch1.txt")
        assert metadata is not None
        assert metadata["extract_status"] == "ok"
        assert metadata["location"] == "Sanctuary"

        characters = ExtractionStore.load_all_characters(conn)
        assert len(characters) == 1
        assert characters[0]["name"] == "Amelia"

        terms = ExtractionStore.load_all_terms(conn)
        assert len(terms) == 1
        assert terms[0]["term"] == "Aether"

        events = ExtractionStore.load_thread_events(conn, "who_stole_the_key")
        assert len(events) == 1
        assert events[0]["event_type"] == "opened"

        timeline = ExtractionStore.load_all_timeline(conn)
        assert len(timeline) == 1
        assert timeline[0]["summary"] == "Amelia notices the key is missing"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_extract_scene_knowledge_raises_on_malformed_response():
    conn = _conn()
    try:
        client = StubClient(responses=["not valid json"])

        with pytest.raises(ValueError, match="not valid JSON"):
            await extraction_service.extract_scene_knowledge(
                scene_content="Scene body",
                scene_filename="text/ch1.txt",
                canon_text="canon",
                existing_knowledge={},
                client=client,
                model="test-model",
                max_tokens=500,
                conn=conn,
            )

        assert ExtractionStore.load_scene_metadata(conn, "text/ch1.txt") is None
    finally:
        conn.close()


def test_aggregate_threads_marks_resolved_when_closed_event_exists():
    conn = _conn()
    try:
        ExtractionStore.upsert_thread(
            conn,
            thread_id="who_stole_the_key",
            question="Who stole the key?",
            status="active",
        )
        ExtractionStore.upsert_thread_event(
            conn,
            thread_id="who_stole_the_key",
            scene_filename="text/ch1.txt",
            event_type="opened",
            notes="Key missing",
        )
        ExtractionStore.upsert_thread_event(
            conn,
            thread_id="who_stole_the_key",
            scene_filename="text/ch2.txt",
            event_type="advanced",
            notes="New witness",
        )
        ExtractionStore.upsert_thread_event(
            conn,
            thread_id="who_stole_the_key",
            scene_filename="text/ch3.txt",
            event_type="closed",
            notes="Confession",
        )

        rows = extraction_service.aggregate_threads(conn)
        assert len(rows) == 1
        thread = rows[0]
        assert thread["thread_id"] == "who_stole_the_key"
        assert thread["status"] == "resolved"
        assert thread["opened_in"] == "text/ch1.txt"
        assert thread["last_advanced"] == "text/ch3.txt"
        assert thread["resolved_in"] == "text/ch3.txt"
        assert thread["question"] == "Who stole the key?"
        assert thread["notes"] == "Confession"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_extract_stale_scenes_skips_locked_scenes(monkeypatch, tmp_path: Path):
    project_path = tmp_path
    (project_path / "CANON.md").write_text("Canon", encoding="utf-8")
    (project_path / "text").mkdir()
    (project_path / "text" / "locked.txt").write_text("locked scene", encoding="utf-8")
    (project_path / "text" / "stale.txt").write_text("stale scene", encoding="utf-8")

    conn = _conn()
    try:
        ExtractionStore.lock_scene(conn, "text/locked.txt")
        client = StubClient(
            responses=[
                json.dumps(
                    {
                        "scene_metadata": {"location": "Room"},
                        "characters": [],
                        "terms": [],
                        "thread_events": [],
                        "timeline": {},
                    }
                )
            ]
        )
        result = await extraction_service.extract_stale_scenes(
            project_path=project_path,
            conn=conn,
            client=client,
            model="test-model",
            max_tokens=500,
            scene_keys=["text/locked.txt", "text/stale.txt"],
        )

        assert result["skipped_locked"] == ["text/locked.txt"]
        assert result["extracted"] == ["text/stale.txt"]
        assert result["failed"] == []

        locked = ExtractionStore.load_scene_metadata(conn, "text/locked.txt")
        assert locked is not None
        assert locked["extraction_locked"] == 1

        stale = ExtractionStore.load_scene_metadata(conn, "text/stale.txt")
        assert stale is not None
        assert stale["extract_status"] == "ok"
        assert len(client.calls) == 1
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_extract_stale_scenes_marks_failed_when_extraction_raises(
    monkeypatch,
    tmp_path: Path,
):
    project_path = tmp_path
    (project_path / "CANON.md").write_text("Canon", encoding="utf-8")
    (project_path / "text").mkdir()
    fail_scene = project_path / "text" / "fail.txt"
    fail_scene.write_text("This extraction will fail", encoding="utf-8")

    conn = _conn()
    try:
        client = StubClient(error=RuntimeError("timeout"))

        result = await extraction_service.extract_stale_scenes(
            project_path=project_path,
            conn=conn,
            client=client,
            model="test-model",
            max_tokens=500,
            scene_keys=["text/fail.txt"],
        )

        assert result["extracted"] == []
        assert result["skipped_locked"] == []
        assert len(result["failed"]) == 1
        assert result["failed"][0]["scene_filename"] == "text/fail.txt"
        assert "timeout" in result["failed"][0]["error"]

        metadata = ExtractionStore.load_scene_metadata(conn, "text/fail.txt")
        assert metadata is not None
        assert metadata["extract_status"] == "failed"
        assert metadata["content_hash"] == compute_file_hash(fail_scene)
    finally:
        conn.close()


def test_persist_scene_payload_skips_locked_character():
    """Locked characters must not be updated during _persist_scene_payload."""
    conn = _conn()
    try:
        # Seed a character with known traits and lock it
        ExtractionStore.upsert_character(conn, name="Amelia", category="main")
        ExtractionStore.lock_entity(conn, "characters", "Amelia")

        payload = {
            "scene_metadata": {},
            "characters": [{"name": "Amelia", "category": "updated"}],
            "terms": [],
            "thread_events": [],
            "timeline": {},
        }
        extraction_service._persist_scene_payload(
            conn=conn,
            scene_filename="text/ch1.txt",
            scene_content="some content",
            payload=payload,
        )

        chars = ExtractionStore.load_all_characters(conn)
        amelia = next(c for c in chars if c["name"] == "Amelia")
        # category should NOT have been updated
        assert amelia["category"] == "main"
    finally:
        conn.close()


def test_persist_scene_payload_updates_unlocked_character():
    """Unlocked characters ARE updated during _persist_scene_payload."""
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Iris", category="supporting")

        payload = {
            "scene_metadata": {},
            "characters": [{"name": "Iris", "category": "main"}],
            "terms": [],
            "thread_events": [],
            "timeline": {},
        }
        extraction_service._persist_scene_payload(
            conn=conn,
            scene_filename="text/ch1.txt",
            scene_content="some content",
            payload=payload,
        )

        chars = ExtractionStore.load_all_characters(conn)
        iris = next(c for c in chars if c["name"] == "Iris")
        assert iris["category"] == "main"
    finally:
        conn.close()


def test_persist_scene_payload_skips_locked_term():
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Aether", definition="old definition")
        ExtractionStore.lock_entity(conn, "terms", "Aether")

        payload = {
            "scene_metadata": {},
            "characters": [],
            "terms": [{"term": "Aether", "definition": "new definition"}],
            "thread_events": [],
            "timeline": {},
        }
        extraction_service._persist_scene_payload(conn, "text/ch1.txt", "content", payload)

        terms = ExtractionStore.load_all_terms(conn)
        aether = next(t for t in terms if t["term"] == "Aether")
        assert aether["definition"] == "old definition"
    finally:
        conn.close()


def test_persist_scene_payload_skips_locked_timeline():
    conn = _conn()
    try:
        ExtractionStore.upsert_timeline(conn, scene_filename="text/ch1.txt", summary="old summary")
        ExtractionStore.lock_entity(conn, "timeline", "text/ch1.txt")

        payload = {
            "scene_metadata": {},
            "characters": [],
            "terms": [],
            "thread_events": [],
            "timeline": {"summary": "new summary"},
        }
        extraction_service._persist_scene_payload(conn, "text/ch1.txt", "content", payload)

        timeline = ExtractionStore.load_all_timeline(conn)
        entry = next((t for t in timeline if t["scene_filename"] == "text/ch1.txt"), None)
        # Locked entry is preserved: DELETE is skipped and no re-insert occurs
        assert entry is not None
        assert entry["summary"] == "old summary"
    finally:
        conn.close()


# --- Tests for reconcile_knowledge() ---


def test_reconcile_updates_applied_to_unlocked_character():
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Amelia", category="supporting")

        llm_output = json.dumps({
            "updates": [{"category": "characters", "entity_key": "Amelia", "field": "category", "new_value": "main"}],
            "removals": [],
        })
        result = reconcile_knowledge(conn, llm_output)

        assert result["applied_updates"] == 1
        assert result["applied_removals"] == 0
        assert result["flagged_for_review"] == []

        chars = ExtractionStore.load_all_characters(conn)
        amelia = next(c for c in chars if c["name"] == "Amelia")
        assert amelia["category"] == "main"
    finally:
        conn.close()


def test_reconcile_updates_skipped_for_locked_character():
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Amelia", category="supporting")
        ExtractionStore.lock_entity(conn, "characters", "Amelia")

        llm_output = json.dumps({
            "updates": [{"category": "characters", "entity_key": "Amelia", "field": "category", "new_value": "main"}],
            "removals": [],
        })
        result = reconcile_knowledge(conn, llm_output)

        assert result["applied_updates"] == 0

        chars = ExtractionStore.load_all_characters(conn)
        amelia = next(c for c in chars if c["name"] == "Amelia")
        assert amelia["category"] == "supporting"  # unchanged
    finally:
        conn.close()


def test_reconcile_removal_no_overrides_deletes_entity():
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Aether", definition="Subtle energy")

        llm_output = json.dumps({
            "updates": [],
            "removals": [{"category": "terms", "entity_key": "Aether", "reason": "No longer referenced"}],
        })
        result = reconcile_knowledge(conn, llm_output)

        assert result["applied_removals"] == 1
        assert result["flagged_for_review"] == []

        terms = ExtractionStore.load_all_terms(conn)
        assert not any(t["term"] == "Aether" for t in terms)
    finally:
        conn.close()


def test_reconcile_removal_with_overrides_flagged_not_deleted():
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Aether", definition="Old definition")
        KnowledgeOverrideStore.upsert_override(
            conn, category="terms", entity_key="Aether",
            field_name="definition", value="Author-corrected definition",
        )

        llm_output = json.dumps({
            "updates": [],
            "removals": [{"category": "terms", "entity_key": "Aether", "reason": "No longer referenced"}],
        })
        result = reconcile_knowledge(conn, llm_output)

        assert result["applied_removals"] == 0
        assert len(result["flagged_for_review"]) == 1
        assert result["flagged_for_review"][0]["entity_key"] == "Aether"
        assert result["flagged_for_review"][0]["category"] == "terms"

        # Entity still exists
        terms = ExtractionStore.load_all_terms(conn)
        assert any(t["term"] == "Aether" for t in terms)
    finally:
        conn.close()


def test_reconcile_removal_skips_locked_entity():
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Iris")
        ExtractionStore.lock_entity(conn, "characters", "Iris")

        llm_output = json.dumps({
            "updates": [],
            "removals": [{"category": "characters", "entity_key": "Iris", "reason": "No longer in story"}],
        })
        result = reconcile_knowledge(conn, llm_output)

        assert result["applied_removals"] == 0
        assert result["flagged_for_review"] == []

        chars = ExtractionStore.load_all_characters(conn)
        assert any(c["name"] == "Iris" for c in chars)
    finally:
        conn.close()


def test_reconcile_invalid_json_returns_empty_result():
    conn = _conn()
    try:
        result = reconcile_knowledge(conn, "not valid json")
        assert result["applied_updates"] == 0
        assert result["applied_removals"] == 0
        assert result["flagged_for_review"] == []
    finally:
        conn.close()


# --- Tests for _build_scene_summaries_text_for_reconciliation and rename detection ---


def test_scene_summaries_include_cast_present():
    """Scene summary lines include Cast: field from cast_present metadata."""
    from orchestrator.services.project_knowledge_service import (
        _build_scene_summaries_text_for_reconciliation,
    )

    conn = _conn()
    try:
        ExtractionStore.upsert_scene_metadata(
            conn,
            scene_filename="ch1.txt",
            content_hash="abc",
            extract_status="ok",
            location="The Market",
            objective="Buy supplies",
            cast_present=json.dumps(["Alice", "Bob"]),
        )

        summary = _build_scene_summaries_text_for_reconciliation(conn)

        assert "Cast: Alice, Bob" in summary
        assert "Scene: ch1.txt" in summary
        assert "Location: The Market" in summary
        assert "Objective: Buy supplies" in summary
    finally:
        conn.close()


def test_reconcile_rename_removal_deletes_unlocked_character():
    """Rename-detection removal: unlocked character deleted; with override it is flagged."""
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="OldName", category="main")

        llm_output = json.dumps({
            "updates": [],
            "removals": [{
                "category": "characters",
                "entity_key": "OldName",
                "reason": "character no longer appears in any scene cast list — possible rename to NewName",
            }],
        })
        result = reconcile_knowledge(conn, llm_output)

        assert result["applied_removals"] == 1
        assert result["flagged_for_review"] == []
        chars = ExtractionStore.load_all_characters(conn)
        assert not any(c["name"] == "OldName" for c in chars)

        # Now re-seed with an override and confirm it is flagged instead
        ExtractionStore.upsert_character(conn, name="OldName", category="main")
        KnowledgeOverrideStore.upsert_override(
            conn, category="characters", entity_key="OldName",
            field_name="category", value="main",
        )

        result2 = reconcile_knowledge(conn, llm_output)

        assert result2["applied_removals"] == 0
        assert len(result2["flagged_for_review"]) == 1
        assert result2["flagged_for_review"][0]["entity_key"] == "OldName"
        # Character still exists because of override
        chars2 = ExtractionStore.load_all_characters(conn)
        assert any(c["name"] == "OldName" for c in chars2)
    finally:
        conn.close()


# --- Tests for ExtractionStore.find_orphaned_characters/terms ---


def test_find_orphaned_characters_returns_characters_with_no_sources():
    """Characters with no rows in extracted_character_sources are reported as orphans."""
    conn = _conn()
    try:
        # Seed two characters; only one has a source row
        ExtractionStore.upsert_character(conn, name="Alice", category="main")
        ExtractionStore.upsert_character(conn, name="Bob", category="supporting")
        ExtractionStore.upsert_character_source(conn, name="Alice", scene_filename="ch1.txt")
        # Bob has no source row — orphan

        orphans = ExtractionStore.find_orphaned_characters(conn)

        assert orphans == ["Bob"]
    finally:
        conn.close()


def test_find_orphaned_characters_empty_when_all_sourced():
    """No orphans reported when every character has at least one source scene."""
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Alice", category="main")
        ExtractionStore.upsert_character_source(conn, name="Alice", scene_filename="ch1.txt")

        orphans = ExtractionStore.find_orphaned_characters(conn)

        assert orphans == []
    finally:
        conn.close()


def test_find_orphaned_terms_returns_terms_with_no_sources():
    """Terms with no rows in extracted_term_sources are reported as orphans."""
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Aether", definition="Subtle energy")
        ExtractionStore.upsert_term(conn, term="Nexus", definition="Focal point")
        ExtractionStore.upsert_term_source(conn, term="Aether", scene_filename="ch1.txt")
        # Nexus has no source row — orphan

        orphans = ExtractionStore.find_orphaned_terms(conn)

        assert orphans == ["Nexus"]
    finally:
        conn.close()


# --- Tests for cleanup_orphaned_entities() ---


def test_cleanup_removes_orphaned_character_with_no_sources_or_overrides():
    """Unlocked, override-free character with zero sources is deleted by cleanup."""
    from orchestrator.services.extraction_service import cleanup_orphaned_entities

    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Ghost", category="minor")
        # No source row — Ghost is an orphan

        result = cleanup_orphaned_entities(conn)

        assert len(result["removed"]) == 1
        assert result["removed"][0] == {"category": "characters", "entity_key": "Ghost"}
        assert result["flagged_for_review"] == []

        chars = ExtractionStore.load_all_characters(conn)
        assert not any(c["name"] == "Ghost" for c in chars)
    finally:
        conn.close()


def test_cleanup_removes_orphaned_term_with_no_sources_or_overrides():
    """Unlocked, override-free term with zero sources is deleted by cleanup."""
    from orchestrator.services.extraction_service import cleanup_orphaned_entities

    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Voidstone", definition="Rare mineral")
        # No source row — Voidstone is an orphan

        result = cleanup_orphaned_entities(conn)

        assert len(result["removed"]) == 1
        assert result["removed"][0] == {"category": "terms", "entity_key": "Voidstone"}

        terms = ExtractionStore.load_all_terms(conn)
        assert not any(t["term"] == "Voidstone" for t in terms)
    finally:
        conn.close()


def test_cleanup_preserves_sourced_character():
    """A character that still has at least one source scene is NOT cleaned up."""
    from orchestrator.services.extraction_service import cleanup_orphaned_entities

    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Alice", category="main")
        ExtractionStore.upsert_character_source(conn, name="Alice", scene_filename="ch1.txt")

        result = cleanup_orphaned_entities(conn)

        assert result["removed"] == []
        assert result["flagged_for_review"] == []

        chars = ExtractionStore.load_all_characters(conn)
        assert any(c["name"] == "Alice" for c in chars)
    finally:
        conn.close()


def test_cleanup_preserves_locked_orphan():
    """A locked character with zero sources is NOT removed — lock takes priority."""
    from orchestrator.services.extraction_service import cleanup_orphaned_entities

    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Phantom", category="minor")
        ExtractionStore.lock_entity(conn, "characters", "Phantom")
        # No source row — orphan, but locked

        result = cleanup_orphaned_entities(conn)

        assert result["removed"] == []
        assert result["flagged_for_review"] == []

        chars = ExtractionStore.load_all_characters(conn)
        assert any(c["name"] == "Phantom" for c in chars)
    finally:
        conn.close()


def test_cleanup_flags_orphan_with_overrides_instead_of_deleting():
    """An orphaned character with author overrides is flagged for review, not deleted."""
    from orchestrator.services.extraction_service import cleanup_orphaned_entities

    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Shadow", category="supporting")
        KnowledgeOverrideStore.upsert_override(
            conn, category="characters", entity_key="Shadow",
            field_name="category", value="main",
        )
        # No source row — orphan, but has author override

        result = cleanup_orphaned_entities(conn)

        assert result["removed"] == []
        assert len(result["flagged_for_review"]) == 1
        flagged = result["flagged_for_review"][0]
        assert flagged["category"] == "characters"
        assert flagged["entity_key"] == "Shadow"
        assert "review" in flagged["reason"]

        # Character must still exist
        chars = ExtractionStore.load_all_characters(conn)
        assert any(c["name"] == "Shadow" for c in chars)
    finally:
        conn.close()


# --- Tests for _apply_entity_field_update PK-field guard ---


def test_apply_entity_field_update_blocks_pk_field_for_terms():
    """Updating the PK field 'term' must be silently ignored — no new row created."""
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Μονή", definition="Monastery")

        _apply_entity_field_update(conn, "terms", "Μονή", "term", "Ιερά Μονή Πεντέλης")

        terms = ExtractionStore.load_all_terms(conn)
        # Original row intact, no second row created
        assert len(terms) == 1
        assert terms[0]["term"] == "Μονή"
        assert terms[0]["definition"] == "Monastery"
    finally:
        conn.close()


def test_apply_entity_field_update_blocks_pk_field_for_characters():
    """Updating the PK field 'name' must be silently ignored — no duplicate created."""
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Amelia", category="main")

        _apply_entity_field_update(conn, "characters", "Amelia", "name", "Lia")

        chars = ExtractionStore.load_all_characters(conn)
        assert len(chars) == 1
        assert chars[0]["name"] == "Amelia"
        assert chars[0]["category"] == "main"
    finally:
        conn.close()


def test_apply_entity_field_update_blocks_pk_field_for_threads():
    """Updating the PK field 'thread_id' must be silently ignored."""
    conn = _conn()
    try:
        ExtractionStore.upsert_thread(conn, thread_id="t1", question="What happened?")

        _apply_entity_field_update(conn, "threads", "t1", "thread_id", "t1_renamed")

        threads = ExtractionStore.load_all_threads(conn)
        assert len(threads) == 1
        assert threads[0]["thread_id"] == "t1"
    finally:
        conn.close()


def test_apply_entity_field_update_blocks_pk_field_for_timeline():
    """Updating the PK field 'scene_filename' must be silently ignored."""
    conn = _conn()
    try:
        ExtractionStore.upsert_timeline(conn, scene_filename="ch1.txt", summary="Opening")

        _apply_entity_field_update(conn, "timeline", "ch1.txt", "scene_filename", "renamed.txt")

        timeline = ExtractionStore.load_all_timeline(conn)
        assert len(timeline) == 1
        assert timeline[0]["scene_filename"] == "ch1.txt"
    finally:
        conn.close()


def test_apply_entity_field_update_allows_non_pk_field_for_terms():
    """Updating a non-PK field ('definition') must be applied normally."""
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Aether", definition="Old definition")

        _apply_entity_field_update(conn, "terms", "Aether", "definition", "New definition")

        terms = ExtractionStore.load_all_terms(conn)
        aether = next(t for t in terms if t["term"] == "Aether")
        assert aether["definition"] == "New definition"
    finally:
        conn.close()


def test_apply_entity_field_update_allows_non_pk_field_for_characters():
    """Updating a non-PK field ('category') must be applied normally."""
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Iris", category="supporting")

        _apply_entity_field_update(conn, "characters", "Iris", "category", "main")

        chars = ExtractionStore.load_all_characters(conn)
        iris = next(c for c in chars if c["name"] == "Iris")
        assert iris["category"] == "main"
    finally:
        conn.close()


# --- Tests for _apply_overrides_with_annotations and _build_existing_knowledge_summary ---


def test_apply_overrides_with_annotations_term_pk_override():
    """A term with a PK-field override gets original_term and user_curated_fields."""
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Μονή", definition="Monastery", category="place")
        KnowledgeOverrideStore.upsert_override(
            conn, category="terms", entity_key="Μονή",
            field_name="term", value="Ιερά Μονή Πεντέλης",
        )

        raw = ExtractionStore.load_all_terms(conn)
        result = _apply_overrides_with_annotations(conn, "terms", raw, "term")

        assert len(result) == 1
        entry = result[0]
        assert entry["term"] == "Ιερά Μονή Πεντέλης"
        assert entry["original_term"] == "Μονή"
        assert entry["user_curated_fields"] == ["term"]
        assert entry["category"] == "place"
        assert entry["definition"] == "Monastery"
    finally:
        conn.close()


def test_apply_overrides_with_annotations_non_overridden_entity_unchanged():
    """An entity with no overrides is returned unchanged — no extra keys added."""
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Aether", definition="Subtle energy")

        raw = ExtractionStore.load_all_terms(conn)
        result = _apply_overrides_with_annotations(conn, "terms", raw, "term")

        assert len(result) == 1
        entry = result[0]
        assert entry["term"] == "Aether"
        assert "original_term" not in entry
        assert "user_curated_fields" not in entry
    finally:
        conn.close()


def test_apply_overrides_with_annotations_non_pk_field_override():
    """A non-PK field override adds original_<field> and user_curated_fields."""
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Alice", category="supporting")
        KnowledgeOverrideStore.upsert_override(
            conn, category="characters", entity_key="Alice",
            field_name="category", value="main",
        )

        raw = ExtractionStore.load_all_characters(conn)
        result = _apply_overrides_with_annotations(conn, "characters", raw, "name")

        assert len(result) == 1
        entry = result[0]
        assert entry["category"] == "main"
        assert entry["original_category"] == "supporting"
        assert entry["user_curated_fields"] == ["category"]
        # PK field untouched
        assert entry["name"] == "Alice"
    finally:
        conn.close()


def test_build_existing_knowledge_summary_applies_overrides():
    """_build_existing_knowledge_summary returns JSON with overrides and annotations."""
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Μονή", definition="Monastery", category="place")
        KnowledgeOverrideStore.upsert_override(
            conn, category="terms", entity_key="Μονή",
            field_name="term", value="Ιερά Μονή Πεντέλης",
        )

        summary_json = _build_existing_knowledge_summary(conn)
        snapshot = json.loads(summary_json)

        terms = snapshot["terms"]
        assert len(terms) == 1
        term_entry = terms[0]
        assert term_entry["term"] == "Ιερά Μονή Πεντέλης"
        assert term_entry["original_term"] == "Μονή"
        assert term_entry["user_curated_fields"] == ["term"]
    finally:
        conn.close()


def test_build_existing_knowledge_summary_no_override_no_annotation():
    """Entities without overrides appear in the summary without annotation keys."""
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Aether", definition="Subtle energy")
        ExtractionStore.upsert_character(conn, name="Alice", category="main")

        summary_json = _build_existing_knowledge_summary(conn)
        snapshot = json.loads(summary_json)

        terms = snapshot["terms"]
        assert len(terms) == 1
        assert "original_term" not in terms[0]
        assert "user_curated_fields" not in terms[0]

        chars = snapshot["characters"]
        assert len(chars) == 1
        assert "original_name" not in chars[0]
        assert "user_curated_fields" not in chars[0]
    finally:
        conn.close()
