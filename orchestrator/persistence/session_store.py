"""Platform-owned session store."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from orchestrator.persistence.path_utils import to_absolute, to_relative


class SessionStore:
    """CRUD operations for review sessions."""

    @staticmethod
    def _encode_scene_paths(scene_paths: list[str]) -> str:
        """Encode scene paths list for persistence in the legacy scene_path column."""
        return json.dumps(scene_paths)

    @staticmethod
    def _decode_scene_paths(raw_scene_path: str | None) -> list[str]:
        """Decode persisted scene_path payload into a normalized path list."""
        if not raw_scene_path:
            return []
        try:
            parsed = json.loads(raw_scene_path)
            if isinstance(parsed, list):
                return [str(p) for p in parsed if p]
        except (json.JSONDecodeError, TypeError):
            pass
        return [raw_scene_path]

    @staticmethod
    def _normalize_scene_paths(
        scene_path: str | None = None,
        scene_paths: list[str] | None = None,
    ) -> list[str]:
        """Normalize single/multi scene path inputs into a non-empty list when possible."""
        if scene_paths:
            return [str(p) for p in scene_paths if p]
        if scene_path:
            return [scene_path]
        return []

    @staticmethod
    def create(conn: sqlite3.Connection, scene_path: str, scene_hash: str,
               model: str, glossary_issues: list[str] | None = None,
               discussion_model: str | None = None,
               depth_mode: str | None = None,
               frontier_model: str | None = None,
               checker_model: str | None = None,
               scene_paths: list[str] | None = None,
               index_context_hash: str = "",
               index_context_stale: bool = False,
               index_rerun_prompted: bool = False,
               index_changed_files: list[str] | None = None,
               project_path: Path | None = None) -> int:
        """Insert a new active session. Returns the session id."""
        normalized_scene_paths = SessionStore._normalize_scene_paths(scene_path, scene_paths)
        if not normalized_scene_paths:
            raise ValueError("create() requires at least one scene path")

        stored_scene_paths = [to_relative(project_path, p) for p in normalized_scene_paths]
        stored_changed_files = [to_relative(project_path, f) for f in (index_changed_files or [])]

        now = datetime.now().isoformat()
        resolved_depth_mode = depth_mode or "deep"
        resolved_checker_model = checker_model or model
        resolved_frontier_model = frontier_model or discussion_model or model
        cursor = conn.execute(
            """INSERT INTO session
               (scene_path, scene_hash, model, discussion_model,
                depth_mode, frontier_model, checker_model,
                glossary_issues, created_at,
                index_context_hash, index_context_stale, index_rerun_prompted, index_changed_files)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (SessionStore._encode_scene_paths(stored_scene_paths), scene_hash, model, discussion_model,
             resolved_depth_mode, resolved_frontier_model, resolved_checker_model,
             json.dumps(glossary_issues or []), now,
             index_context_hash, int(index_context_stale), int(index_rerun_prompted),
             json.dumps(stored_changed_files)),
        )
        conn.commit()
        return cursor.lastrowid

    @staticmethod
    def load_active(conn: sqlite3.Connection, project_path: Path | None = None) -> Optional[dict]:
        """Load the active session, or None if no active session exists."""
        row = conn.execute(
            "SELECT * FROM session WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return SessionStore._row_to_dict(row, project_path=project_path)

    @staticmethod
    def exists_active(conn: sqlite3.Connection) -> bool:
        """Check whether an active session exists."""
        row = conn.execute(
            "SELECT 1 FROM session WHERE status = 'active' LIMIT 1"
        ).fetchone()
        return row is not None

    @staticmethod
    def get(conn: sqlite3.Connection, session_id: int, project_path: Path | None = None) -> Optional[dict]:
        """Load a single session by id."""
        row = conn.execute(
            "SELECT * FROM session WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return SessionStore._row_to_dict(row, project_path=project_path)

    @staticmethod
    def list_all(conn: sqlite3.Connection, project_path: Path | None = None) -> list[dict]:
        """List all sessions, newest first."""
        rows = conn.execute(
            "SELECT * FROM session ORDER BY id DESC"
        ).fetchall()
        return [SessionStore._row_to_dict(r, project_path=project_path) for r in rows]

    @staticmethod
    def update_glossary_issues(conn: sqlite3.Connection, session_id: int,
                               glossary_issues: list[str]) -> None:
        """Update glossary issues."""
        conn.execute(
            "UPDATE session SET glossary_issues = ? WHERE id = ?",
            (json.dumps(glossary_issues), session_id),
        )
        conn.commit()

    @staticmethod
    def update_scene(conn: sqlite3.Connection, session_id: int,
                     scene_hash: str) -> None:
        """Update scene hash after a scene change detection."""
        conn.execute(
            "UPDATE session SET scene_hash = ? WHERE id = ?",
            (scene_hash, session_id),
        )
        conn.commit()

    @staticmethod
    def update_scene_path(conn: sqlite3.Connection, session_id: int,
                          scene_path: str, project_path: Path | None = None) -> None:
        """Update the persisted scene path for a session."""
        SessionStore.update_scene_paths(conn, session_id, [scene_path], project_path=project_path)

    @staticmethod
    def update_scene_paths(conn: sqlite3.Connection, session_id: int,
                           scene_paths: list[str], project_path: Path | None = None) -> None:
        """Update the persisted ordered scene path set for a session."""
        normalized_scene_paths = SessionStore._normalize_scene_paths(scene_paths=scene_paths)
        if not normalized_scene_paths:
            raise ValueError("update_scene_paths() requires at least one scene path")
        stored = [to_relative(project_path, p) for p in normalized_scene_paths]
        conn.execute(
            "UPDATE session SET scene_path = ? WHERE id = ?",
            (SessionStore._encode_scene_paths(stored), session_id),
        )
        conn.commit()

    @staticmethod
    def update_index_context(
        conn: sqlite3.Connection,
        session_id: int,
        *,
        index_context_hash: str,
        index_context_stale: bool,
        index_rerun_prompted: bool,
        index_changed_files: list[str],
        project_path: Path | None = None,
    ) -> None:
        """Update all index-context tracking fields at once."""
        stored_changed = [to_relative(project_path, f) for f in index_changed_files]
        conn.execute(
            """UPDATE session SET
                   index_context_hash = ?,
                   index_context_stale = ?,
                   index_rerun_prompted = ?,
                   index_changed_files = ?
               WHERE id = ?""",
            (
                index_context_hash,
                int(index_context_stale),
                int(index_rerun_prompted),
                json.dumps(stored_changed),
                session_id,
            ),
        )
        conn.commit()

    @staticmethod
    def mark_index_context_stale(
        conn: sqlite3.Connection,
        session_id: int,
        *,
        changed_files: list[str],
        prompted: bool | None = None,
        project_path: Path | None = None,
    ) -> None:
        """Mark index context stale and persist changed file names."""
        stored_changed = [to_relative(project_path, f) for f in changed_files]
        if prompted is None:
            conn.execute(
                """UPDATE session SET
                       index_context_stale = 1,
                       index_changed_files = ?
                   WHERE id = ?""",
                (json.dumps(stored_changed), session_id),
            )
        else:
            conn.execute(
                """UPDATE session SET
                       index_context_stale = 1,
                       index_rerun_prompted = ?,
                       index_changed_files = ?
                   WHERE id = ?""",
                (int(prompted), json.dumps(stored_changed), session_id),
            )
        conn.commit()

    @staticmethod
    def clear_index_context_stale(
        conn: sqlite3.Connection,
        session_id: int,
        *,
        index_context_hash: str,
    ) -> None:
        """Clear stale state after re-run and set a fresh context hash."""
        conn.execute(
            """UPDATE session SET
                   index_context_hash = ?,
                   index_context_stale = 0,
                   index_rerun_prompted = 0,
                   index_changed_files = '[]'
               WHERE id = ?""",
            (index_context_hash, session_id),
        )
        conn.commit()

    @staticmethod
    def update_counts(conn: sqlite3.Connection, session_id: int) -> bool:
        """Recalculate and update finding counts for a session."""
        stats = conn.execute(
            """SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) AS accepted,
                   SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected,
                   SUM(CASE WHEN status = 'withdrawn' THEN 1 ELSE 0 END) AS withdrawn
               FROM finding WHERE session_id = ?""",
            (session_id,),
        ).fetchone()

        accepted = int(stats["accepted"] or 0)
        rejected = int(stats["rejected"] or 0)
        withdrawn = int(stats["withdrawn"] or 0)
        current = conn.execute(
            """SELECT accepted_count, rejected_count, withdrawn_count
               FROM session WHERE id = ?""",
            (session_id,),
        ).fetchone()
        if current is None:
            return False

        if (
            int(current["accepted_count"] or 0) == accepted
            and int(current["rejected_count"] or 0) == rejected
            and int(current["withdrawn_count"] or 0) == withdrawn
        ):
            return False

        conn.execute(
            """UPDATE session SET
                   accepted_count = ?,
                   rejected_count = ?,
                   withdrawn_count = ?
               WHERE id = ?""",
            (accepted, rejected, withdrawn, session_id),
        )
        conn.commit()
        return True

    @staticmethod
    def complete(conn: sqlite3.Connection, session_id: int) -> None:
        """Mark a session as completed and tally stats from its findings."""
        now = datetime.now().isoformat()

        stats = conn.execute(
            """SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) AS accepted,
                   SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected,
                   SUM(CASE WHEN status = 'withdrawn' THEN 1 ELSE 0 END) AS withdrawn
               FROM finding WHERE session_id = ?""",
            (session_id,),
        ).fetchone()

        conn.execute(
            """UPDATE session SET
                   status = 'completed', completed_at = ?,
                   total_findings = ?, accepted_count = ?,
                   rejected_count = ?, withdrawn_count = ?
               WHERE id = ?""",
            (now, stats["total"], stats["accepted"],
             stats["rejected"], stats["withdrawn"], session_id),
        )
        conn.commit()

    @staticmethod
    def reopen(conn: sqlite3.Connection, session_id: int) -> None:
        """Re-open a completed session back to active status."""
        conn.execute(
            "UPDATE session SET status = 'active', completed_at = NULL WHERE id = ?",
            (session_id,),
        )
        conn.commit()

    @staticmethod
    def abandon(conn: sqlite3.Connection, session_id: int) -> None:
        """Mark a session as abandoned."""
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE session SET status = 'abandoned', completed_at = ? WHERE id = ?",
            (now, session_id),
        )
        conn.commit()

    @staticmethod
    def delete(conn: sqlite3.Connection, session_id: int) -> bool:
        """Delete a session and its findings. Returns True if a row was deleted."""
        cursor = conn.execute(
            "DELETE FROM session WHERE id = ?", (session_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def delete_all(conn: sqlite3.Connection) -> int:
        """Delete all sessions and their findings. Returns the number of sessions deleted."""
        count = conn.execute("SELECT COUNT(*) FROM session").fetchone()[0]
        conn.execute("DELETE FROM finding")
        conn.execute("DELETE FROM session")
        conn.commit()
        return count

    @staticmethod
    def validate(session_data: dict, scene_content_hash: str,
                 scene_path: str, project_path: Path | None = None) -> tuple[bool, str]:
        """Validate that a saved session matches the current scene."""
        if not session_data:
            return False, "No session data"

        scene_paths = session_data.get("scene_paths") or []
        if scene_paths:
            # Absolutize stored paths (may be relative after migration) before comparing
            abs_saved = {
                str((to_absolute(project_path, p) or Path(p)).resolve())
                for p in scene_paths
            }
            if str(Path(scene_path).resolve()) not in abs_saved:
                return False, f"Session is for different scene set: {scene_paths}"
        else:
            saved_scene_path = session_data.get("scene_path", "")
            abs_saved_path = (to_absolute(project_path, saved_scene_path) or Path(saved_scene_path))
            if abs_saved_path.resolve() != Path(scene_path).resolve():
                return False, f"Session is for different scene: {saved_scene_path}"

        saved_hash = session_data.get("scene_hash", "")
        if saved_hash != scene_content_hash:
            return False, "Scene file has been modified since session was saved"

        return True, ""

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, project_path: Path | None = None) -> dict:
        """Convert a sqlite3.Row to a plain dict, deserialising JSON columns."""
        d = dict(row)
        d["depth_mode"] = d.get("depth_mode") or "deep"
        d["checker_model"] = d.get("checker_model") or d.get("model")
        d["frontier_model"] = (
            d.get("frontier_model") or d.get("discussion_model") or d.get("model")
        )
        scene_paths = SessionStore._decode_scene_paths(d.get("scene_path"))
        # Absolutize relative paths stored after v13 migration
        if project_path is not None:
            scene_paths = [
                str(to_absolute(project_path, p) or Path(p)) for p in scene_paths
            ]
        d["scene_paths"] = scene_paths
        d["scene_path"] = scene_paths[0] if scene_paths else ""
        for key in ("glossary_issues", "index_changed_files"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    d[key] = []
        # Absolutize index_changed_files after JSON decode
        if project_path is not None and isinstance(d.get("index_changed_files"), list):
            d["index_changed_files"] = [
                str(to_absolute(project_path, f) or Path(f))
                for f in d["index_changed_files"]
                if f
            ]
        if "stale" in d:
            d["stale"] = bool(d["stale"])
        if "index_context_stale" in d:
            d["index_context_stale"] = bool(d["index_context_stale"])
        if "index_rerun_prompted" in d:
            d["index_rerun_prompted"] = bool(d["index_rerun_prompted"])
        return d


__all__ = ["SessionStore"]
