"""Project-knowledge projection orchestration helpers."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path

from orchestrator.persistence import IndexProjectionStore, SceneProjectionStore
from orchestrator.persistence.database import get_connection, get_passive_connection
from orchestrator.runtime.config import MAX_TOKENS, resolve_api_key, resolve_model
from orchestrator.runtime.llm import create_client
import logging

from orchestrator.runtime.model_slots import SLOT_QUICK, default_model_slots

logger = logging.getLogger(__name__)

from core.log_utils import op_start, op_complete
from orchestrator.persistence.extraction_store import ExtractionStore
from orchestrator.persistence.knowledge_state_store import KnowledgeStateStore
from orchestrator.runtime.prompts import get_knowledge_reconciliation_prompt
from orchestrator.services.extraction_service import (
    _apply_overrides_with_annotations,
    cleanup_orphaned_entities,
    extract_stale_scenes,
    reconcile_knowledge,
)
from orchestrator.user_config import get_knowledge_review_pass_setting
from orchestrator.services.index_projection_service import refresh_index_projection
from orchestrator.services.index_status_service import (
    IndexStatus,
    list_index_statuses,
)
from orchestrator.services.scene_projection_service import (
    discover_scene_relative_paths,
    refresh_all_scenes,
)
from orchestrator.services.scene_status_service import (
    SceneStatus,
    list_scene_statuses,
)

_INDEX_FILENAMES = (
    "CANON.md",
    "STYLE.md",
)

# ---------------------------------------------------------------------------
# Per-project refresh lock — prevents concurrent extractions for the same
# project (e.g. when multiple requests arrive before the first completes).
# ---------------------------------------------------------------------------
_refresh_locks: dict[str, threading.Lock] = {}
_refresh_locks_mutex = threading.Lock()


def _get_refresh_lock(project_root: Path) -> threading.Lock:
    """Return the dedicated threading.Lock for *project_root*, creating it if absent."""
    key = str(project_root.resolve())
    with _refresh_locks_mutex:
        if key not in _refresh_locks:
            _refresh_locks[key] = threading.Lock()
        return _refresh_locks[key]


def refresh_project_knowledge(
    project_path: Path,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Refresh scene projections, chain validation, extraction, and canon/style projections.

    At most one refresh runs per project at a time.  Concurrent callers receive
    an immediate ``"refresh_in_progress"`` response rather than blocking or
    running duplicate LLM extraction.
    """
    project_root = Path(project_path)

    # Non-blocking acquire: if another thread is already refreshing this project,
    # return immediately so the caller (e.g. a second auto-save event) doesn't
    # queue up duplicate LLM work.
    lock = _get_refresh_lock(project_root)
    if not lock.acquire(blocking=False):
        return {
            "scenes": [],
            "indexes": [],
            "scene_total": 0,
            "scene_updated": 0,
            "index_total": 0,
            "index_updated": 0,
            "chain_warnings": [],
            "extraction": _empty_extraction_result(reason="refresh_in_progress"),
        }

    try:
        staleness = get_project_knowledge_staleness(project_root)
        stale_scenes = staleness["stale_scenes"]
        stale_indexes = staleness["stale_indexes"]
        if not stale_scenes and not stale_indexes:
            return {
                "scenes": [],
                "indexes": [],
                "scene_total": 0,
                "scene_updated": 0,
                "index_total": 0,
                "index_updated": 0,
                "chain_warnings": [],
                "extraction": _empty_extraction_result(reason="no_stale_scenes"),
            }

        owns_connection = conn is None
        active_conn = conn or get_connection(project_root)

        # Re-extraction resolves staleness — clear the persisted cache so the
        # tree view doesn't show stale indicators from a previous "Check" run.
        KnowledgeStateStore.clear_staleness_cache(active_conn)

        try:
            scene_results = refresh_all_scenes(project_root, active_conn)
            index_results = _refresh_canon_style_indexes(project_root, active_conn)
            chain_warnings = _validate_prev_next_chain(
                project_root,
                SceneProjectionStore.load_all(active_conn, project_path=project_root),
            )
            # Compute which scenes to extract — single authority via scene_status_service.
            # When CANON.md changed, all scenes need re-extraction regardless of hash.
            if "CANON.md" in stale_indexes:
                extraction_scene_keys = discover_scene_relative_paths(project_root)
            else:
                _status_records = list_scene_statuses(project_root, active_conn)
                extraction_scene_keys = [
                    r.scene_key for r in _status_records
                    if r.current_hash is not None
                    and r.status == SceneStatus.extraction_due
                ]
            extraction = _refresh_extracted_knowledge(
                project_root,
                active_conn,
                should_attempt=bool(stale_scenes) or "CANON.md" in stale_indexes,
                scene_keys=extraction_scene_keys,
            )
            return {
                "scenes": scene_results,
                "indexes": index_results,
                "scene_total": len(scene_results),
                "scene_updated": sum(1 for row in scene_results if row.get("updated")),
                "index_total": len(index_results),
                "index_updated": sum(1 for row in index_results if row.get("updated")),
                "chain_warnings": chain_warnings,
                "extraction": extraction,
            }
        finally:
            if owns_connection:
                active_conn.close()
    finally:
        lock.release()


def get_project_knowledge_staleness(project_path: Path) -> dict[str, list[str]]:
    """Return stale scene/index keys using passive DB reads when possible."""
    project_root = Path(project_path)
    conn = get_passive_connection(project_root)
    if conn is None:
        return {
            "stale_scenes": sorted(_discover_scene_relative_paths(project_root)),
            "stale_indexes": sorted(_existing_index_names(project_root)),
        }
    try:
        scene_records = list_scene_statuses(project_root, conn)
        stale_scenes = [
            r.scene_key for r in scene_records
            if r.current_hash is not None and r.status != SceneStatus.analyzed
        ]
        index_records = list_index_statuses(project_root, conn)
        stale_indexes = [
            r.index_name for r in index_records
            if r.status == IndexStatus.stale
            or (r.status == IndexStatus.absent and r.stored_hash is not None)
        ]
        return {"stale_scenes": stale_scenes, "stale_indexes": stale_indexes}
    except sqlite3.OperationalError:
        return {
            "stale_scenes": sorted(_discover_scene_relative_paths(project_root)),
            "stale_indexes": sorted(_existing_index_names(project_root)),
        }
    finally:
        conn.close()


def get_project_knowledge_status(project_path: Path) -> dict:
    """Return stale/fresh counts and latest refresh timestamps for projections."""
    project_root = Path(project_path)
    conn = get_passive_connection(project_root)
    if conn is None:
        # DB does not exist yet — return zeroes rather than triggering DB creation.
        return {
            "scenes": {"total": 0, "stale": 0, "fresh": 0, "last_refreshed_at": None},
            "indexes": {"total": 0, "stale": 0, "fresh": 0, "last_refreshed_at": None},
            "stale_total": 0,
            "fresh_total": 0,
        }
    try:
        scene_records = list_scene_statuses(project_root, conn)
        stale_scenes = [
            r.scene_key for r in scene_records
            if r.current_hash is not None and r.status != SceneStatus.analyzed
        ]
        index_records = list_index_statuses(project_root, conn)
        stale_indexes = [
            r.index_name for r in index_records
            if r.status == IndexStatus.stale
            or (r.status == IndexStatus.absent and r.stored_hash is not None)
        ]

        scene_rows = SceneProjectionStore.load_all(conn, project_path=project_root)
        index_rows = IndexProjectionStore.load_all(conn)

        scene_total = len(
            {
                _normalize_scene_key(project_root, row["scene_path"])
                for row in scene_rows
            }
            | set(_discover_scene_relative_paths(project_root))
        )
        index_total = len(
            {Path(row["index_name"]).name for row in index_rows}
            | _existing_index_names(project_root)
        )

        scene_last_refreshed = max(
            (row.get("last_refreshed_at") for row in scene_rows if row.get("last_refreshed_at")),
            default=None,
        )
        index_last_refreshed = max(
            (row.get("last_refreshed_at") for row in index_rows if row.get("last_refreshed_at")),
            default=None,
        )

        scene_fresh = max(scene_total - len(stale_scenes), 0)
        index_fresh = max(index_total - len(stale_indexes), 0)

        return {
            "scenes": {
                "total": scene_total,
                "stale": len(stale_scenes),
                "fresh": scene_fresh,
                "last_refreshed_at": scene_last_refreshed,
            },
            "indexes": {
                "total": index_total,
                "stale": len(stale_indexes),
                "fresh": index_fresh,
                "last_refreshed_at": index_last_refreshed,
            },
            "stale_total": len(stale_scenes) + len(stale_indexes),
            "fresh_total": scene_fresh + index_fresh,
        }
    except sqlite3.OperationalError:
        return {
            "scenes": {"total": 0, "stale": 0, "fresh": 0, "last_refreshed_at": None},
            "indexes": {"total": 0, "stale": 0, "fresh": 0, "last_refreshed_at": None},
            "stale_total": 0,
            "fresh_total": 0,
        }
    finally:
        conn.close()


def ensure_project_knowledge_fresh(
    project_path: Path,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Refresh projections only if any scene/index source appears stale."""
    project_root = Path(project_path)

    staleness = get_project_knowledge_staleness(project_root)
    stale_scenes = staleness["stale_scenes"]
    stale_indexes = staleness["stale_indexes"]
    if not stale_scenes and not stale_indexes:
        return {
            "refreshed": False,
            "stale_scenes": [],
            "stale_indexes": [],
        }

    refreshed = refresh_project_knowledge(project_root, conn=conn)
    refreshed["refreshed"] = True
    refreshed["stale_scenes"] = stale_scenes
    refreshed["stale_indexes"] = stale_indexes
    return refreshed


def detect_orphaned_scene_data(project_path: Path) -> dict:
    """Return sessions and silence rules that reference deleted scene files.

    Uses ``_find_orphaned_scene_keys()`` to identify scene keys in the DB that no
    longer exist on disk, then returns which sessions and silence rules reference
    each orphaned key.

    Returns::

        {
            "orphaned_scenes": [
                {
                    "scene_key": "text/she_wakes_up.md",
                    "affected_sessions": [1, 3],
                    "affected_silence_rules": [2],
                }
            ]
        }
    """
    from orchestrator.persistence.session_store import SessionStore

    project_root = Path(project_path)
    conn = get_passive_connection(project_root)
    if conn is None:
        return {"orphaned_scenes": []}
    try:
        orphan_keys = _find_orphaned_scene_keys(project_root, conn)
        if not orphan_keys:
            return {"orphaned_scenes": []}

        try:
            all_sessions = SessionStore.list_all(conn, project_path=project_root)
        except sqlite3.OperationalError:
            all_sessions = []  # session table removed in v22

        # Map orphaned filenames → orphan key for session scene_path matching
        orphan_key_by_filename: dict[str, str] = {
            Path(key).name: key for key in orphan_keys
        }

        # Collect sessions per orphan key
        sessions_by_key: dict[str, set[int]] = {key: set() for key in orphan_keys}
        for session in all_sessions:
            for sp in session.get("scene_paths") or []:
                filename = Path(sp).name
                if filename in orphan_key_by_filename:
                    sessions_by_key[orphan_key_by_filename[filename]].add(session["id"])

        # Collect silence rules per orphan key (scope='scene')
        silence_by_key: dict[str, set[int]] = {key: set() for key in orphan_keys}
        try:
            silence_rows = conn.execute(
                "SELECT id, scene_path FROM silence_rule WHERE scope = 'scene'"
            ).fetchall()
            for row in silence_rows:
                raw_path = row["scene_path"] or ""
                normalized = _normalize_scene_key(project_root, raw_path)
                if normalized in silence_by_key:
                    silence_by_key[normalized].add(row["id"])
                elif Path(normalized).name in orphan_key_by_filename:
                    silence_by_key[orphan_key_by_filename[Path(normalized).name]].add(row["id"])
        except sqlite3.OperationalError:
            pass  # silence_rule table may not exist in older DBs

        return {
            "orphaned_scenes": [
                {
                    "scene_key": key,
                    "affected_sessions": sorted(sessions_by_key[key]),
                    "affected_silence_rules": sorted(silence_by_key[key]),
                }
                for key in orphan_keys
            ]
        }
    finally:
        conn.close()


def _discover_scene_relative_paths(project_root: Path) -> list[str]:
    """Discover scene files using configured folder/extensions."""
    return discover_scene_relative_paths(project_root)


def _scene_hashes_by_normalized_key(
    project_root: Path,
    conn: sqlite3.Connection,
) -> dict[str, str]:
    """Load stored scene hashes indexed by normalized scene keys."""
    normalized_hashes: dict[str, str] = {}
    for row in SceneProjectionStore.load_all(conn, project_path=project_root):
        normalized_hashes[_normalize_scene_key(project_root, row["scene_path"])] = row[
            "file_hash"
        ]
    return normalized_hashes


def _normalize_scene_key(project_root: Path, scene_key: str) -> str:
    """Normalize scene keys to project-root-relative POSIX paths when possible."""
    candidate = Path(scene_key)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(project_root).as_posix()
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def _find_orphaned_scene_keys(project_root: Path, conn: sqlite3.Connection) -> list[str]:
    """Return normalized scene keys that are in the DB but no longer exist on disk."""
    stored_hashes = _scene_hashes_by_normalized_key(project_root, conn)
    existing = set(_discover_scene_relative_paths(project_root))
    return sorted(set(stored_hashes) - existing)


def purge_deleted_scene_data(
    conn: sqlite3.Connection,
    project_root: Path,
    orphan_keys: list[str],
) -> dict:
    """Remove derived/extraction DB data for scene files that have been deleted.

    Cleans up:
    - scene_projection
    - extracted_scene_metadata
    - extracted_character_sources
    - extracted_term_sources
    - extracted_thread_events
    - extracted_timeline

    Does NOT touch sessions, findings, silence_rules, or analysis_snapshots —
    those contain user data and are left as inert orphans.

    After removing source links, calls cleanup_orphaned_entities() so that any
    character or term whose last source scene was deleted is also removed.

    Returns {"purged": <count of scene keys removed>}.
    """
    if not orphan_keys:
        return {"purged": 0}

    for scene_key in orphan_keys:
        op_start("purge_scene_data", scene_key)
        scene_filename = Path(scene_key).name
        # Projection table — keyed by relative scene path
        SceneProjectionStore.delete_by_path(conn, scene_key, project_path=project_root)
        # Extraction tables — keyed by basename
        conn.execute(
            "DELETE FROM extracted_scene_metadata WHERE scene_filename = ?",
            (scene_filename,),
        )
        conn.execute(
            "DELETE FROM extracted_character_sources WHERE scene_filename = ?",
            (scene_filename,),
        )
        conn.execute(
            "DELETE FROM extracted_term_sources WHERE scene_filename = ?",
            (scene_filename,),
        )
        conn.execute(
            "DELETE FROM extracted_thread_events WHERE scene_filename = ?",
            (scene_filename,),
        )
        conn.execute(
            "DELETE FROM extracted_timeline WHERE scene_filename = ?",
            (scene_filename,),
        )
        op_complete("purge_scene_data", scene_key, status="ok")

    conn.commit()

    # Remove characters/terms that lost their last source scene
    cleanup_orphaned_entities(conn)

    return {"purged": len(orphan_keys)}


def _existing_index_names(project_root: Path) -> set[str]:
    """Return canonical index filenames that currently exist on disk."""
    return {name for name in _INDEX_FILENAMES if (project_root / name).exists()}


def _refresh_canon_style_indexes(
    project_root: Path,
    conn: sqlite3.Connection,
) -> list[dict]:
    """Refresh only authored canon/style index projections."""
    results: list[dict] = []
    for index_name in _INDEX_FILENAMES:
        index_file = project_root / index_name
        if not index_file.exists():
            continue
        results.append(refresh_index_projection(project_root, index_name, conn))
    return results


def _refresh_extracted_knowledge(
    project_root: Path,
    conn: sqlite3.Connection,
    *,
    should_attempt: bool,
    scene_keys: list[str],
) -> dict:
    """Run extraction for *scene_keys* using the hardcoded quick model slot.

    *scene_keys* are pre-computed by the caller using ``scene_status_service``
    (or ``discover_scene_relative_paths`` for the CANON.md-changed case) and
    are forwarded directly to ``extract_stale_scenes`` — no staleness re-check
    is performed inside the extraction service.
    """
    if not should_attempt:
        return _empty_extraction_result(reason="no_stale_scenes")

    try:
        extraction_model = default_model_slots()[SLOT_QUICK]
        model_cfg = resolve_model(extraction_model)
        provider = str(model_cfg["provider"])
        model_id = str(model_cfg["id"])
        max_tokens = int(model_cfg.get("max_tokens") or MAX_TOKENS)
        api_key = resolve_api_key(provider)
        client = create_client(provider, api_key)

        try:
            if _is_running_in_event_loop():
                result = _run_coro_sync(
                    _extract_stale_scenes_with_fresh_connection(
                        project_root=project_root,
                        client=client,
                        model=model_id,
                        max_tokens=max_tokens,
                        scene_keys=scene_keys,
                    )
                )
            else:
                result = _run_coro_sync(
                    extract_stale_scenes(
                        project_path=project_root,
                        conn=conn,
                        client=client,
                        model=model_id,
                        max_tokens=max_tokens,
                        scene_keys=scene_keys,
                    )
                )
            result["attempted"] = True
            result["reason"] = "partial_failure" if result.get("failed") else "ok"
            result["model_slot"] = SLOT_QUICK
            result["model_name"] = extraction_model

            # Reconciliation review pass
            result["flagged_for_review"] = _run_reconciliation_pass(
                project_root=project_root,
                client=client,
                model_id=model_id,
                max_tokens=max_tokens,
                extraction_result=result,
            )

            # Persist flags so they survive restarts and DB copies
            KnowledgeStateStore.save_review_flags(conn, result["flagged_for_review"])

            return result
        finally:
            # Explicitly close the httpx transport while an event loop is still
            # available.  Without this, garbage collection later triggers
            # AsyncClient.aclose() after asyncio.run() has torn down its loop,
            # causing "RuntimeError: Event loop is closed" on Windows.
            # The call is best-effort: test doubles and future clients that
            # don't define aclose() are silently skipped.
            _aclose = getattr(client, "aclose", None)
            if _aclose is not None:
                try:
                    _run_coro_sync(_aclose())
                except Exception:  # noqa: BLE001 - transport cleanup is non-fatal
                    logger.debug("Failed to close LLM client transport (non-fatal)", exc_info=True)
    except Exception as exc:  # noqa: BLE001 - refresh should remain non-fatal
        return _empty_extraction_result(
            reason="extraction_unavailable",
            error=str(exc),
        )


def _empty_extraction_result(reason: str, error: str | None = None) -> dict:
    """Build a consistent extraction result payload for skipped/failed attempts."""
    payload: dict = {
        "attempted": False,
        "reason": reason,
        "scenes_scanned": 0,
        "extracted": [],
        "skipped_locked": [],
        "failed": [],
    }
    if error:
        payload["error"] = error
    return payload


async def _extract_stale_scenes_with_fresh_connection(
    *,
    project_root: Path,
    client,
    model: str,
    max_tokens: int,
    scene_keys: list[str],
) -> dict:
    """Run extraction with a connection opened on the executing thread."""
    extraction_conn = get_connection(project_root)
    try:
        return await extract_stale_scenes(
            project_path=project_root,
            conn=extraction_conn,
            client=client,
            model=model,
            max_tokens=max_tokens,
            scene_keys=scene_keys,
        )
    finally:
        extraction_conn.close()


def _is_running_in_event_loop() -> bool:
    """Return ``True`` when called from within an active asyncio event loop."""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _run_coro_sync(coro):
    """Run a coroutine from sync code, including when already inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_box: dict[str, dict] = {}
    error_box: dict[str, Exception] = {}

    def _runner() -> None:
        try:
            result_box["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            error_box["value"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "value" in error_box:
        raise error_box["value"]
    return result_box.get("value", {})


def _validate_prev_next_chain(project_root: Path, scene_rows: list[dict]) -> list[dict]:
    """Validate Prev/Next graph and return non-fatal chain warnings."""
    if not scene_rows:
        return []

    normalized_rows = {
        _normalize_scene_key(project_root, str(row.get("scene_path") or "")): row
        for row in scene_rows
    }
    scene_paths = sorted(path for path in normalized_rows if path)
    scene_set = set(scene_paths)
    if not scene_paths:
        return []

    prev_refs: dict[str, str | None] = {}
    next_refs: dict[str, str | None] = {}
    incoming: dict[str, int] = {}
    next_claims: dict[str, list[str]] = {}
    warnings: list[dict] = []

    for scene_path in scene_paths:
        meta = _coerce_meta_json(normalized_rows[scene_path].get("meta_json"))
        prev_ref = _normalize_chain_ref(meta.get("prev"))
        next_ref = _normalize_chain_ref(meta.get("next"))
        prev_refs[scene_path] = prev_ref
        next_refs[scene_path] = next_ref

        if prev_ref and prev_ref not in scene_set:
            warnings.append(
                {
                    "type": "gap",
                    "scene": scene_path,
                    "field": "prev",
                    "target": prev_ref,
                }
            )
        if next_ref and next_ref not in scene_set:
            warnings.append(
                {
                    "type": "gap",
                    "scene": scene_path,
                    "field": "next",
                    "target": next_ref,
                }
            )

        if next_ref and next_ref in scene_set:
            incoming[next_ref] = incoming.get(next_ref, 0) + 1
            next_claims.setdefault(next_ref, []).append(scene_path)

    for target, sources in sorted(next_claims.items()):
        if len(sources) > 1:
            warnings.append(
                {
                    "type": "fork",
                    "target": target,
                    "sources": sorted(sources),
                }
            )

    visited: set[str] = set()
    seen_cycles: set[tuple[str, ...]] = set()
    for start in scene_paths:
        if start in visited:
            continue
        order: list[str] = []
        positions: dict[str, int] = {}
        current: str | None = start

        while current and current in scene_set and current not in visited:
            if current in positions:
                cycle = tuple(order[positions[current] :])
                if cycle and cycle not in seen_cycles:
                    warnings.append({"type": "cycle", "scenes": list(cycle)})
                    seen_cycles.add(cycle)
                break
            positions[current] = len(order)
            order.append(current)
            next_ref = next_refs.get(current)
            if not next_ref or next_ref not in scene_set:
                break
            current = next_ref

        visited.update(order)

    if len(scene_paths) > 1:
        for scene_path in scene_paths:
            has_incoming = incoming.get(scene_path, 0) > 0
            next_ref = next_refs.get(scene_path)
            has_outgoing = bool(next_ref and next_ref in scene_set)
            if not has_incoming and not has_outgoing:
                warnings.append({"type": "orphan", "scene": scene_path})

    return warnings


def _coerce_meta_json(raw_meta: object) -> dict[str, str]:
    """Normalize stored projection metadata to a dict for chain validation."""
    if isinstance(raw_meta, dict):
        return raw_meta
    if isinstance(raw_meta, str):
        try:
            parsed = json.loads(raw_meta)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalize_chain_ref(value: object) -> str | None:
    """Normalize a Prev/Next reference value to a canonical scene key."""
    if value is None:
        return None
    ref = str(value).strip()
    if not ref:
        return None
    if ref.lower() in {"none", "null", "tbd", "n/a", "na"}:
        return None
    return Path(ref).as_posix()


def _run_reconciliation_pass(
    *,
    project_root: Path,
    client,
    model_id: str,
    max_tokens: int,
    extraction_result: dict,
) -> list[dict]:
    """Run the knowledge reconciliation review pass after extraction.

    Returns a (possibly empty) list of flagged-for-review items.
    Skips gracefully on any error so it never breaks the refresh flow.
    """
    trigger = get_knowledge_review_pass_setting()
    if trigger == "never":
        return []
    if trigger == "on_stale" and not extraction_result.get("extracted"):
        return []

    try:
        conn = get_connection(project_root)
        try:
            # --- Step 1: deterministic orphan cleanup (no LLM needed) ---
            # After extraction, any character/term with zero remaining source rows
            # is definitively absent from all scene text. Remove them immediately.
            op_start("reconcile_knowledge", "orphan_cleanup")
            orphan_result = cleanup_orphaned_entities(conn)
            op_complete(
                "reconcile_knowledge", "orphan_cleanup",
                removed=len(orphan_result.get("removed", [])),
                flagged=len(orphan_result.get("flagged_for_review", [])),
            )
            all_flagged = list(orphan_result.get("flagged_for_review", []))

            # --- Step 2: LLM reconciliation for field updates and subtler removals ---
            op_start("reconcile_knowledge", "llm_pass")
            knowledge_json = _build_knowledge_json_for_reconciliation(conn)
            scene_summaries_text = _build_scene_summaries_text_for_reconciliation(conn)
            prompt = get_knowledge_reconciliation_prompt(knowledge_json, scene_summaries_text)
            llm_output = _run_coro_sync(
                _call_llm_for_reconciliation(client, model_id, max_tokens, prompt)
            )
            rec_result = reconcile_knowledge(conn, llm_output)
            op_complete(
                "reconcile_knowledge", "llm_pass",
                updates=rec_result.get("applied_updates", 0),
                removals=rec_result.get("applied_removals", 0),
                flagged=len(rec_result.get("flagged_for_review", [])),
            )
            # Merge LLM-flagged items, deduplicating by (category, entity_key)
            seen_keys = {
                (item["category"], item["entity_key"]) for item in all_flagged
            }
            for item in rec_result.get("flagged_for_review", []):
                key = (item["category"], item["entity_key"])
                if key not in seen_keys:
                    all_flagged.append(item)
                    seen_keys.add(key)

            return all_flagged
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - reconciliation is non-fatal
        logger.warning("Reconciliation pass failed (non-fatal): %s", exc)
        return []


def _build_knowledge_json_for_reconciliation(conn: sqlite3.Connection) -> str:
    """Serialize extracted knowledge as JSON with overrides applied.

    Entities that have author overrides are annotated with ``original_<field>``
    companion keys and a ``user_curated_fields`` list.  This gives the
    reconciliation LLM both the canonical (override) value and the original
    text anchor so it can correctly evaluate scene support without proposing
    spurious removals or PK renames.
    """
    snapshot = {
        "characters": _apply_overrides_with_annotations(
            conn, "characters", ExtractionStore.load_all_characters(conn), "name"
        ),
        "terms": _apply_overrides_with_annotations(
            conn, "terms", ExtractionStore.load_all_terms(conn), "term"
        ),
        "threads": ExtractionStore.load_all_threads(conn),
        "timeline": ExtractionStore.load_all_timeline(conn),
    }
    return json.dumps(snapshot, ensure_ascii=False)


def _build_scene_summaries_text_for_reconciliation(conn: sqlite3.Connection) -> str:
    """Build a plain-text scene summary block for the reconciliation prompt.

    Each line includes the scene filename, location, objective, and the
    ``cast_present`` list so the reconciliation LLM can detect when a
    character no longer appears in any scene (e.g. after a rename).
    """
    rows = ExtractionStore.load_all_scene_metadata(conn)
    if not rows:
        return "[No scene summaries available]"
    lines: list[str] = []
    for row in rows:
        parts = [f"Scene: {row['scene_filename']}"]
        if row.get("location"):
            parts.append(f"Location: {row['location']}")
        if row.get("objective"):
            parts.append(f"Objective: {row['objective']}")
        raw_cast = row.get("cast_present")
        if raw_cast:
            # cast_present is stored as a JSON list string; parse it gracefully.
            if isinstance(raw_cast, list):
                cast_names = raw_cast
            else:
                try:
                    cast_names = json.loads(raw_cast)
                except (TypeError, ValueError):
                    cast_names = []
            if cast_names:
                parts.append(f"Cast: {', '.join(str(n) for n in cast_names)}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _knowledge_affected_by_scene(
    conn: sqlite3.Connection,
    scene_filename: str,
) -> list[dict]:
    """Return knowledge entries sourced from *scene_filename*."""
    affected: list[dict] = []

    rows = conn.execute(
        "SELECT name FROM extracted_character_sources WHERE scene_filename = ? ORDER BY name",
        (scene_filename,),
    ).fetchall()
    for row in rows:
        affected.append({"category": "characters", "entity_key": row["name"]})

    rows = conn.execute(
        "SELECT term FROM extracted_term_sources WHERE scene_filename = ? ORDER BY term",
        (scene_filename,),
    ).fetchall()
    for row in rows:
        affected.append({"category": "terms", "entity_key": row["term"]})

    rows = conn.execute(
        "SELECT thread_id FROM extracted_thread_events WHERE scene_filename = ? ORDER BY thread_id",
        (scene_filename,),
    ).fetchall()
    for row in rows:
        affected.append({"category": "threads", "entity_key": row["thread_id"]})

    row = conn.execute(
        "SELECT scene_filename FROM extracted_timeline WHERE scene_filename = ?",
        (scene_filename,),
    ).fetchone()
    if row:
        affected.append({"category": "timeline", "entity_key": scene_filename})

    return affected


async def _call_llm_for_reconciliation(
    client, model_id: str, max_tokens: int, prompt: str
) -> str:
    """Call the LLM for the reconciliation prompt and return raw text."""
    response = await client.create_message(
        model=model_id,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.text


__all__ = [
    "ensure_project_knowledge_fresh",
    "get_project_knowledge_staleness",
    "get_project_knowledge_status",
    "refresh_project_knowledge",
]
