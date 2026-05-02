import sqlite3

from orchestrator.persistence.database import init_db
from orchestrator.persistence.extraction_store import ExtractionStore


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_scene_metadata_roundtrip_staleness_and_locking():
    conn = _conn()
    try:
        ExtractionStore.upsert_scene_metadata(
            conn,
            scene_filename="text/ch1.txt",
            content_hash="hash-v1",
            location="Sanctuary",
            pov="Amelia",
            tense="Past",
            tense_notes="Flashback in p3",
            cast_present=["Amelia", "Iris"],
            objective="Find the key",
            cont_anchors={"mood": "tense"},
        )

        row = ExtractionStore.load_scene_metadata(conn, "text/ch1.txt")
        assert row is not None
        assert row["content_hash"] == "hash-v1"
        assert row["location"] == "Sanctuary"
        assert row["pov"] == "Amelia"
        assert row["cast_present"] == ["Amelia", "Iris"]
        assert row["cont_anchors"] == {"mood": "tense"}
        assert row["extract_status"] == "ok"

        all_rows = ExtractionStore.load_all_scene_metadata(conn)
        assert [r["scene_filename"] for r in all_rows] == ["text/ch1.txt"]

        ExtractionStore.mark_scene_stale(conn, "text/ch1.txt", "hash-v2")
        stale_row = ExtractionStore.load_scene_metadata(conn, "text/ch1.txt")
        assert stale_row is not None
        assert stale_row["content_hash"] == "hash-v2"
        assert stale_row["extract_status"] == "stale"

        ExtractionStore.mark_scene_stale(conn, "text/ch2.txt", "hash-new")
        inserted_stale = ExtractionStore.load_scene_metadata(conn, "text/ch2.txt")
        assert inserted_stale is not None
        assert inserted_stale["content_hash"] == "hash-new"
        assert inserted_stale["extract_status"] == "stale"

        ExtractionStore.lock_scene(conn, "text/ch1.txt")
        locked = ExtractionStore.load_scene_metadata(conn, "text/ch1.txt")
        assert locked is not None
        assert locked["extraction_locked"] == 1
        assert locked["locked_at"]

        ExtractionStore.unlock_scene(conn, "text/ch1.txt")
        unlocked = ExtractionStore.load_scene_metadata(conn, "text/ch1.txt")
        assert unlocked is not None
        assert unlocked["extraction_locked"] == 0
        assert unlocked["locked_at"] is None
    finally:
        conn.close()


def test_character_roundtrip_and_row_to_dict_shape():
    conn = _conn()
    try:
        ExtractionStore.upsert_character(
            conn,
            name="Amelia",
            aka=["Lia", "The Seer"],
            category="main",
            traits={"role": "protagonist"},
            relationships=[{"target": "Iris", "description": "mentor"}],
            first_seen="text/ch1.txt",
        )

        rows = ExtractionStore.load_all_characters(conn)
        assert len(rows) == 1
        assert rows[0]["name"] == "Amelia"
        assert rows[0]["aka"] == ["Lia", "The Seer"]
        assert rows[0]["traits"] == {"role": "protagonist"}
        assert rows[0]["relationships"][0]["target"] == "Iris"

        ExtractionStore.upsert_character(
            conn,
            name="Amelia",
            aka=["Amelia"],
            category="supporting",
            traits={"role": "observer"},
            relationships=[{"target": "Tobias", "description": "ally"}],
            first_seen="text/ch0.txt",
        )
        updated = ExtractionStore.load_all_characters(conn)[0]
        assert updated["category"] == "supporting"
        assert updated["traits"]["role"] == "observer"
        assert updated["first_seen"] == "text/ch0.txt"

        raw_row = conn.execute(
            "SELECT * FROM extracted_characters WHERE name = ?", ("Amelia",)
        ).fetchone()
        converted = ExtractionStore._row_to_dict(raw_row)
        assert isinstance(converted["aka"], list)
        assert isinstance(converted["traits"], dict)
        assert isinstance(converted["relationships"], list)
    finally:
        conn.close()


def test_term_thread_event_and_timeline_roundtrip():
    conn = _conn()
    try:
        ExtractionStore.upsert_term(
            conn,
            term="Aether",
            category="term",
            definition="Subtle energy",
            translation="αιθήρ",
            notes="Capitalized",
            first_seen="text/ch1.txt",
        )
        ExtractionStore.upsert_term(
            conn,
            term="Aether",
            category="place",
            definition="Realm",
            translation="",
            notes="Updated",
            first_seen="text/ch2.txt",
        )
        terms = ExtractionStore.load_all_terms(conn)
        assert len(terms) == 1
        assert terms[0]["term"] == "Aether"
        assert terms[0]["category"] == "place"
        assert terms[0]["first_seen"] == "text/ch2.txt"

        ExtractionStore.upsert_thread(
            conn,
            thread_id="who_stole_the_key",
            question="Who stole the key?",
            status="active",
            opened_in="text/ch1.txt",
            last_advanced="text/ch1.txt",
            notes="Introduced in chapter 1",
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
            scene_filename="text/ch2.txt",
            event_type="closed",
            notes="Confession",
        )

        threads = ExtractionStore.load_all_threads(conn)
        assert len(threads) == 1
        assert threads[0]["thread_id"] == "who_stole_the_key"

        filtered_events = ExtractionStore.load_thread_events(
            conn,
            thread_id="who_stole_the_key",
        )
        assert len(filtered_events) == 2
        assert filtered_events[-1]["event_type"] == "closed"

        all_events = ExtractionStore.load_thread_events(conn)
        assert len(all_events) == 2

        ExtractionStore.upsert_timeline(
            conn,
            scene_filename="text/ch1.txt",
            summary="Amelia discovers the theft",
            chrono_hint="Day 1 evening",
        )
        ExtractionStore.upsert_timeline(
            conn,
            scene_filename="text/ch1.txt",
            summary="Amelia identifies the thief",
            chrono_hint="Day 2 morning",
        )
        timeline = ExtractionStore.load_all_timeline(conn)
        assert len(timeline) == 1
        assert timeline[0]["summary"] == "Amelia identifies the thief"
        assert timeline[0]["chrono_hint"] == "Day 2 morning"
    finally:
        conn.close()


def test_entity_lock_unlock_characters():
    conn = _conn()
    try:
        ExtractionStore.upsert_character(conn, name="Amelia")
        ExtractionStore.upsert_character(conn, name="Iris")

        # Initially unlocked
        assert ExtractionStore.is_entity_locked(conn, "characters", "Amelia") is False

        # Lock
        ExtractionStore.lock_entity(conn, "characters", "Amelia")
        assert ExtractionStore.is_entity_locked(conn, "characters", "Amelia") is True

        # locked_at is set
        chars = ExtractionStore.load_all_characters(conn)
        amelia = next(c for c in chars if c["name"] == "Amelia")
        assert amelia["entity_locked"] == 1
        assert amelia["locked_at"] is not None

        # Double-lock is idempotent
        ExtractionStore.lock_entity(conn, "characters", "Amelia")
        assert ExtractionStore.is_entity_locked(conn, "characters", "Amelia") is True

        # Unlock
        ExtractionStore.unlock_entity(conn, "characters", "Amelia")
        assert ExtractionStore.is_entity_locked(conn, "characters", "Amelia") is False
        chars = ExtractionStore.load_all_characters(conn)
        amelia = next(c for c in chars if c["name"] == "Amelia")
        assert amelia["entity_locked"] == 0
        assert amelia["locked_at"] is None

        # get_entity_lock_status returns full map
        ExtractionStore.lock_entity(conn, "characters", "Iris")
        status = ExtractionStore.get_entity_lock_status(conn, "characters")
        assert status == {"Amelia": False, "Iris": True}
    finally:
        conn.close()


def test_entity_lock_unlock_terms():
    conn = _conn()
    try:
        ExtractionStore.upsert_term(conn, term="Sanctuary")

        assert ExtractionStore.is_entity_locked(conn, "terms", "Sanctuary") is False
        ExtractionStore.lock_entity(conn, "terms", "Sanctuary")
        assert ExtractionStore.is_entity_locked(conn, "terms", "Sanctuary") is True
        ExtractionStore.unlock_entity(conn, "terms", "Sanctuary")
        assert ExtractionStore.is_entity_locked(conn, "terms", "Sanctuary") is False

        status = ExtractionStore.get_entity_lock_status(conn, "terms")
        assert status == {"Sanctuary": False}
    finally:
        conn.close()


def test_entity_lock_unlock_threads():
    conn = _conn()
    try:
        ExtractionStore.upsert_thread(conn, thread_id="T-01", question="Who is the thief?")

        assert ExtractionStore.is_entity_locked(conn, "threads", "T-01") is False
        ExtractionStore.lock_entity(conn, "threads", "T-01")
        assert ExtractionStore.is_entity_locked(conn, "threads", "T-01") is True
        ExtractionStore.unlock_entity(conn, "threads", "T-01")
        assert ExtractionStore.is_entity_locked(conn, "threads", "T-01") is False

        status = ExtractionStore.get_entity_lock_status(conn, "threads")
        assert status == {"T-01": False}
    finally:
        conn.close()


def test_entity_lock_unlock_timeline():
    conn = _conn()
    try:
        ExtractionStore.upsert_timeline(conn, scene_filename="text/ch1.txt", summary="Opening")

        assert ExtractionStore.is_entity_locked(conn, "timeline", "text/ch1.txt") is False
        ExtractionStore.lock_entity(conn, "timeline", "text/ch1.txt")
        assert ExtractionStore.is_entity_locked(conn, "timeline", "text/ch1.txt") is True
        ExtractionStore.unlock_entity(conn, "timeline", "text/ch1.txt")
        assert ExtractionStore.is_entity_locked(conn, "timeline", "text/ch1.txt") is False

        status = ExtractionStore.get_entity_lock_status(conn, "timeline")
        assert status == {"text/ch1.txt": False}
    finally:
        conn.close()


def test_is_entity_locked_returns_false_for_missing_entity():
    conn = _conn()
    try:
        # No entity inserted — should return False, not raise
        result = ExtractionStore.is_entity_locked(conn, "characters", "NonExistent")
        assert result is False
    finally:
        conn.close()


def test_reset_clears_all_extraction_tables():
    conn = _conn()
    try:
        # Populate every extraction table
        ExtractionStore.upsert_scene_metadata(conn, scene_filename="text/ch1.txt", content_hash="h1")
        ExtractionStore.upsert_character(conn, name="Amelia")
        ExtractionStore.upsert_character_source(conn, name="Amelia", scene_filename="text/ch1.txt")
        ExtractionStore.upsert_term(conn, term="Aether")
        ExtractionStore.upsert_term_source(conn, term="Aether", scene_filename="text/ch1.txt")
        ExtractionStore.upsert_thread(conn, thread_id="T-01", question="Who?")
        ExtractionStore.upsert_thread_event(conn, thread_id="T-01", scene_filename="text/ch1.txt", event_type="opened")
        ExtractionStore.upsert_timeline(conn, scene_filename="text/ch1.txt", summary="Day 1")

        # Verify data exists before reset
        assert len(ExtractionStore.load_all_characters(conn)) == 1
        assert len(ExtractionStore.load_all_terms(conn)) == 1
        assert len(ExtractionStore.load_all_threads(conn)) == 1
        assert len(ExtractionStore.load_all_timeline(conn)) == 1
        assert len(ExtractionStore.load_all_scene_metadata(conn)) == 1

        ExtractionStore.reset(conn)

        # All tables should now be empty
        assert ExtractionStore.load_all_characters(conn) == []
        assert ExtractionStore.load_all_terms(conn) == []
        assert ExtractionStore.load_all_threads(conn) == []
        assert ExtractionStore.load_all_timeline(conn) == []
        assert ExtractionStore.load_all_scene_metadata(conn) == []
        assert ExtractionStore.load_thread_events(conn) == []
        assert ExtractionStore.load_character_scenes(conn, "Amelia") == []
        assert ExtractionStore.load_term_scenes(conn, "Aether") == []
    finally:
        conn.close()
