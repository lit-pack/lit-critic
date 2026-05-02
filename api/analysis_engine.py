"""
Analysis engine for the REST API.

Bridges the API layer to the orchestrator for running multi-lens analysis.
Extracted from the former WebSessionManager; contains only analysis orchestration
logic, SSE progress tracking, and result building.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from orchestrator.facade import PlatformFacade
from orchestrator.models import SessionState, Finding, CoordinatorError
from orchestrator.runtime.model_slots import resolve_models_for_mode
from orchestrator.runtime.utils import (
    concatenate_scenes,
    map_global_range_to_scene,
    remap_location_line_range,
)
from orchestrator.services.analysis_service import (
    DEFAULT_MODEL,
    create_client,
    is_known_model,
    resolve_model,
    run_coordinator,
    run_coordinator_chunked,
    run_lens,
)
from orchestrator.persistence.database import get_connection as _get_db_conn
from orchestrator.persistence.learning_store import LearningStore
from orchestrator.persistence.snapshot_store import SnapshotStore
from orchestrator.services.code_checks import run_code_checks
from orchestrator.services.project_knowledge_service import ensure_project_knowledge_fresh
from orchestrator.services.session_service import compute_scene_hash as _compute_scene_hash
from orchestrator.services.snapshot_analysis_service import create_snapshot_from_core_findings
from core.domain import SnapshotFinding as _SnapshotFinding
from core.log_utils import op_start, op_complete

from orchestrator.services import (
    load_learning,
    compute_index_context_hash,
    generate_learning_markdown,
    check_active_session,
    complete_active_session,
)

logger = logging.getLogger(__name__)


class AnalysisProgress:
    """Tracks progress of the multi-lens analysis for SSE streaming."""

    def __init__(self):
        self.events: list[dict] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self.complete = False
        self.error: Optional[str] = None

    def add_event(self, event_type: str, data: dict):
        event = {"type": event_type, **data}
        self.events.append(event)
        self._queue.put_nowait(event)

    def drain_replayed(self, count: int) -> None:
        """Discard `count` events from the queue that were already sent via the
        initial replay loop, preventing duplicates when a client connects after
        some events have already been emitted."""
        for _ in range(count):
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def get_event(self) -> dict:
        return await self._queue.get()


class AnalysisEngine:
    """Runs multi-lens analysis and tracks results.

    Single-user, single-analysis-at-a-time engine for the local REST API.
    """

    def __init__(self):
        self.state: Optional[SessionState] = None
        self.results: Optional[dict] = None
        self.analysis_progress: Optional[AnalysisProgress] = None
        self._snapshot_id: Optional[int] = None

    _FRONTIER_LENSES = {"prose", "structure", "horizon"}

    @property
    def is_active(self) -> bool:
        return self.state is not None and self.state.findings

    @property
    def total_findings(self) -> int:
        if not self.state or not self.state.findings:
            return 0
        return len(self.state.findings)

    def _load_project_files(self, project_path: Path) -> dict[str, str]:
        """Load project knowledge context via the Platform facade."""
        return PlatformFacade.load_legacy_indexes_from_project(project_path)

    def _load_scene(self, scene_path: Path) -> str:
        """Load the scene file via Platform layer."""
        if not scene_path.exists():
            raise FileNotFoundError(f"Scene file not found: {scene_path}")
        return PlatformFacade.load_scene_text(scene_path)

    def _load_scenes(self, scene_paths: list[Path]) -> tuple[str, list[dict]]:
        """Load and concatenate scenes into analysis text and line map."""
        scene_docs = [(str(scene), self._load_scene(scene)) for scene in scene_paths]
        return concatenate_scenes(scene_docs)

    async def start_analysis(self, scene_path: str, project_path: str, api_key: str,
                             model: str = DEFAULT_MODEL, discussion_model: str = None,
                             discussion_api_key: str | None = None,
                             scene_paths: list[str] | None = None,
                             depth_mode: str = "deep",
                             frontier_model: str | None = None,
                             checker_model: str | None = None) -> dict:
        """Start a new analysis. Returns summary info. Populates self.state."""
        project = Path(project_path)
        requested_scene_paths = scene_paths or [scene_path]
        scenes = [Path(p) for p in requested_scene_paths]

        if not project.exists():
            raise FileNotFoundError(f"Project directory not found: {project}")

        # Validate legacy model inputs first (transitional compatibility).
        if not is_known_model(model):
            model = DEFAULT_MODEL
        if discussion_model and not is_known_model(discussion_model):
            discussion_model = None

        # Resolve canonical tier assignments for this run.
        candidate_frontier_model = frontier_model or discussion_model or model
        if not is_known_model(candidate_frontier_model):
            candidate_frontier_model = DEFAULT_MODEL

        candidate_checker_model = checker_model or model
        if not is_known_model(candidate_checker_model):
            candidate_checker_model = DEFAULT_MODEL

        op_start("start_analysis", scenes[0].name)

        resolved_models = resolve_models_for_mode(
            depth_mode,
            {
                "frontier": candidate_frontier_model,
                "quick": candidate_checker_model,
                "deep": candidate_checker_model,
            },
        )

        resolved_depth_mode = resolved_models["mode"]
        resolved_frontier_model = resolved_models["frontier_model"]
        resolved_checker_model = resolved_models["checker_model"]

        # Handle existing active session
        active = check_active_session(project)
        if active.get("exists"):
            # Auto-complete the previous session
            complete_active_session(project)

        # Ensure projections + extracted knowledge are fresh for this run.
        ensure_project_knowledge_fresh(project)

        # Load files
        indexes = self._load_project_files(project)
        scene_content, scene_line_map = self._load_scenes(scenes)

        # Load learning and inject directly into indexes so that analysis prompts
        # always reflect the current DB state (no need for a LEARNING.md file on disk).
        learning = load_learning(project)
        indexes['learning'] = generate_learning_markdown(learning)

        # Initialize clients per tier model.
        checker_provider = resolve_model(resolved_checker_model)["provider"]
        client = create_client(checker_provider, api_key)

        frontier_provider = resolve_model(resolved_frontier_model)["provider"]
        if frontier_provider != checker_provider:
            discussion_client = create_client(frontier_provider, discussion_api_key or api_key)
        else:
            discussion_client = client

        # Create session state
        self.state = SessionState(
            client=client,
            scene_content=scene_content,
            scene_path=str(scenes[0]),
            project_path=project,
            indexes=indexes,
            scene_paths=[str(s) for s in scenes],
            scene_line_map=scene_line_map,
            learning=learning,
            depth_mode=resolved_depth_mode,
            frontier_model=resolved_frontier_model,
            checker_model=resolved_checker_model,
            model=resolved_checker_model,
            discussion_model=resolved_frontier_model,
            discussion_client=discussion_client,
            index_context_hash=compute_index_context_hash(indexes),
            index_context_stale=False,
            index_rerun_prompted=False,
            index_changed_files=[],
        )

        # Set up progress tracking
        self.analysis_progress = AnalysisProgress()

        # ------------------------------------------------------------------ #
        # Phase 1: Run deterministic code checks (free, instant)
        # ------------------------------------------------------------------ #
        self.analysis_progress.add_event("status", {"message": "Running code checks..."})
        code_findings = run_code_checks(scene_content, indexes)
        if code_findings:
            self.analysis_progress.add_event("code_checks_complete", {
                "message": f"Code checks: {len(code_findings)} finding(s)",
                "count": len(code_findings),
            })
        else:
            self.analysis_progress.add_event("code_checks_complete", {
                "message": "Code checks: all clear",
                "count": 0,
            })

        # Run analysis with progress tracking
        self.analysis_progress.add_event("status", {"message": "Running 7 lenses in parallel..."})

        checker_model_cfg = resolve_model(self.state.effective_checker_model)
        frontier_model_cfg = resolve_model(self.state.effective_frontier_model)
        checker_client = self.state.client
        frontier_client = self.state.effective_discussion_client

        lens_names = ["prose", "structure", "logic", "clarity", "continuity", "dialogue", "horizon"]
        lens_tasks = [
            self._run_lens_with_progress(
                frontier_client if name in self._FRONTIER_LENSES else checker_client,
                name,
                scene_content,
                indexes,
                model=(
                    frontier_model_cfg["id"]
                    if name in self._FRONTIER_LENSES
                    else checker_model_cfg["id"]
                ),
                max_tokens=(
                    frontier_model_cfg["max_tokens"]
                    if name in self._FRONTIER_LENSES
                    else checker_model_cfg["max_tokens"]
                ),
            )
            for name in lens_names
        ]

        lens_results = await asyncio.gather(*lens_tasks)

        # Check for errors
        for result in lens_results:
            if result.error:
                self.analysis_progress.add_event("warning", {
                    "lens": result.lens_name,
                    "message": f"{result.lens_name} lens failed: {result.error}"
                })

        # Coordinate (chunked: prose -> structure -> coherence)
        self.analysis_progress.add_event("status", {"message": "Coordinating results (chunked)..."})

        def _coord_progress(event_type: str, data: dict):
            self.analysis_progress.add_event(event_type, data)

        # Coordinator always runs on checker tier (quick/deep) to keep
        # aggregation and fallback behavior aligned with checker-model routing.
        coordinator_client = checker_client

        try:
            coordinated = await run_coordinator_chunked(
                coordinator_client, lens_results, scene_content,
                model=checker_model_cfg["id"],
                # Use COORDINATOR_MAX_TOKENS (not the model's per-lens budget) —
                # the coordinator aggregates findings from multiple lenses and
                # needs a much larger output window than a single lens call.
                progress_callback=_coord_progress,
            )
        except CoordinatorError:
            # Fallback to single-call coordinator
            self.analysis_progress.add_event("warning", {
                "message": "Chunked coordinator failed. Falling back to single-call..."
            })
            try:
                coordinated = await run_coordinator(
                    coordinator_client, lens_results, scene_content,
                    model=checker_model_cfg["id"],
                    # Same: let COORDINATOR_MAX_TOKENS default apply here too.
                )
            except CoordinatorError as e:
                error_msg = str(e)
                self.analysis_progress.add_event("error", {"message": f"Coordination error: {error_msg}"})
                self.analysis_progress.complete = True
                self.analysis_progress.error = error_msg
                return {"error": error_msg}

        self.results = coordinated

        # Convert LLM findings to Finding objects.
        # Numbers are offset by the number of code findings so the combined
        # list has a single contiguous sequence: 1..K (code), K+1..K+N (LLM).
        code_count = len(code_findings)
        findings_data = coordinated.get("findings", [])
        llm_findings = [
            Finding(
                number=code_count + f.get('number', i + 1),
                severity=f.get('severity', 'minor'),
                lens=f.get('lens', 'unknown'),
                location=f.get('location', ''),
                line_start=f.get('line_start'),
                line_end=f.get('line_end'),
                evidence=f.get('evidence', ''),
                impact=f.get('impact', ''),
                options=f.get('options', []),
                flagged_by=f.get('flagged_by', []),
                ambiguity_type=f.get('ambiguity_type'),
                origin=f.get('origin', 'legacy'),
            )
            for i, f in enumerate(findings_data)
        ]

        # Combine: code findings first, then LLM findings.
        # Apply scene path / line remapping to all findings.
        self.state.findings = code_findings + llm_findings

        for finding in self.state.findings:
            mapped_scene_path, local_start, local_end = map_global_range_to_scene(
                self.state.scene_line_map,
                finding.line_start,
                finding.line_end,
            )
            finding.scene_path = mapped_scene_path or self.state.scene_path
            finding.line_start = local_start
            finding.line_end = local_end
            finding.location = remap_location_line_range(
                finding.location,
                finding.line_start,
                finding.line_end,
            )
        self.state.glossary_issues = coordinated.get("glossary_issues", [])

        # Persist results as an AnalysisSnapshot (replaces legacy session row).
        _conn = _get_db_conn(project)
        try:
            _findings_by_scene: dict = {}
            for _f in self.state.findings:
                _sp = _f.scene_path or self.state.scene_path
                _findings_by_scene.setdefault(_sp, []).append(_f)

            _scene_hashes: dict[str, str] = {}
            for _scene in scenes:
                try:
                    _scene_hashes[str(_scene)] = _compute_scene_hash(
                        self._load_scene(_scene)
                    )
                except Exception:
                    _scene_hashes[str(_scene)] = ""

            _scene_paths_str = [str(s) for s in scenes]

            # Steps 1–4: resolved-finding detection and snapshot cleanup.
            # Each step is guarded so a failure here does not abort analysis.

            # 1. Load previous findings for each scene.
            _prev_findings: list = []
            for _prev_sp in _scene_paths_str:
                try:
                    _prev_snap = SnapshotStore.get_latest_for_scene(
                        _conn, _prev_sp, project_path=project
                    )
                    if _prev_snap and _prev_snap.findings:
                        _prev_findings.extend(_prev_snap.findings)
                except Exception:
                    logger.warning(
                        "start_analysis: could not load previous snapshot for %s",
                        _prev_sp,
                    )

            # 2+3. Detect resolved findings and persist resolution learning entries.
            if _prev_findings:
                try:
                    _new_corr_keys: set[str] = set()
                    from orchestrator.persistence.path_utils import to_relative
                    for _nf in self.state.findings:
                        _sp = _nf.scene_path or self.state.scene_path
                        _rel_sp = to_relative(project, _sp)
                        _nk = _SnapshotFinding.build_correlation_key(
                            _rel_sp,
                            _nf.lens,
                            _nf.line_start,
                            _nf.evidence,
                        )
                        if _nk:
                            _new_corr_keys.add(_nk)

                    _resolved = [
                        pf for pf in _prev_findings
                        if pf.state != "resolved"
                        and pf.correlation_key not in _new_corr_keys
                    ]
                    if _resolved:
                        for _rf in _resolved:
                            _desc = (
                                "Resolved: "
                                + ((_rf.evidence or "")[:80] or _rf.lens or "unknown")
                            )
                            LearningStore.add_resolution(_conn, _desc)
                except Exception:
                    logger.warning(
                        "start_analysis: could not process resolved findings"
                    )

            # 4. Delete old snapshots for these scenes so only one snapshot per
            #    scene exists after this run.
            try:
                SnapshotStore.delete_for_scenes(_conn, _scene_paths_str, project_path=project)
            except Exception:
                logger.warning("start_analysis: could not delete old snapshots")

            # 5. Persist new findings as the replacement snapshot.
            _snapshot = create_snapshot_from_core_findings(
                _conn,
                scene_paths=_scene_paths_str,
                findings_by_scene=_findings_by_scene,
                depth_mode=resolved_depth_mode,
                scene_hashes=_scene_hashes,
                index_context_hash=self.state.index_context_hash,
                frontier_model=resolved_frontier_model,
                checker_model=resolved_checker_model,
                quick_model=resolved_checker_model,
                project_path=project,
            )
            self._snapshot_id = _snapshot.id
        finally:
            _conn.close()

        self.analysis_progress.add_event("complete", {
            "message": "Analysis complete",
            "total_findings": len(self.state.findings)
        })
        self.analysis_progress.complete = True

        op_complete("start_analysis", scenes[0].name, status="ok", findings=len(self.state.findings))
        return self._build_summary()

    async def _run_lens_with_progress(self, client, lens_name, scene, indexes,
                                      model=None, max_tokens=None):
        """Run a single lens and emit progress event on completion."""
        kwargs = {}
        if model is not None:
            kwargs["model"] = model
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        result = await run_lens(client, lens_name, scene, indexes, **kwargs)
        if result.error:
            self.analysis_progress.add_event("lens_error", {
                "lens": lens_name,
                "message": result.error
            })
        else:
            self.analysis_progress.add_event("lens_complete", {
                "lens": lens_name
            })
        return result

    def _build_summary(self) -> dict:
        """Build the summary response dict."""
        if not self.state:
            return {}

        summary = {
            "scene_path": self.state.scene_path,
            "scene_paths": self.state.scene_paths or [self.state.scene_path],
            "scene_name": Path(self.state.scene_path).name,
            "project_path": str(self.state.project_path),
            "total_findings": len(self.state.findings),
            "current_index": 0,
            "glossary_issues": self.state.glossary_issues,
            "counts": {"critical": 0, "major": 0, "minor": 0},
            "lens_counts": {},
            "read_only": False,
            "session_status": "active",
        }

        for f in self.state.findings:
            sev = f.severity.lower()
            if sev in summary["counts"]:
                summary["counts"][sev] += 1
            lens = f.lens.lower()
            if lens not in summary["lens_counts"]:
                summary["lens_counts"][lens] = {"critical": 0, "major": 0, "minor": 0}
            if sev in summary["lens_counts"][lens]:
                summary["lens_counts"][lens][sev] += 1

        # Model info
        summary["model"] = {
            "name": self.state.model,
            "id": self.state.model_id,
            "label": self.state.model_label,
        }

        # Discussion summary is pinned to the frontier tier model.
        summary["discussion_model"] = {
            "name": self.state.effective_frontier_model,
            "id": resolve_model(self.state.effective_frontier_model)["id"],
            "label": resolve_model(self.state.effective_frontier_model)["label"],
        }

        # Learning info
        summary["learning"] = {
            "review_count": self.state.learning.review_count,
            "preferences": len(self.state.learning.preferences),
            "blind_spots": len(self.state.learning.blind_spots),
        }

        # Session ID — prefer snapshot id (new model)
        if self._snapshot_id:
            summary["session_id"] = self._snapshot_id

        summary["index_context_stale"] = self.state.index_context_stale
        summary["index_changed_files"] = self.state.index_changed_files
        summary["rerun_recommended"] = self.state.index_context_stale
        summary["index_change"] = {
            "changed": self.state.index_context_stale,
            "stale": self.state.index_context_stale,
            "changed_files": self.state.index_changed_files,
            "prompt": False,
        }

        # Include findings_status for direct population of findings tree in VS Code extension
        # This eliminates the need for a fragile second HTTP call to GET /api/session
        summary["findings_status"] = [
            {
                "number": f.number,
                "severity": f.severity,
                "lens": f.lens,
                "status": f.status,
                "location": f.location,
                "evidence": f.evidence,
                "line_start": f.line_start,
                "line_end": f.line_end,
                "scene_path": f.scene_path,
            }
            for f in self.state.findings
        ]

        return summary

    def get_session_info(self) -> dict:
        """Get current session state info."""
        if not self.state:
            return {"active": False}

        return {
            "active": True,
            **self._build_summary(),
            "findings_status": [
                {
                    "number": f.number,
                    "severity": f.severity,
                    "lens": f.lens,
                    "status": f.status,
                    "location": f.location,
                    "evidence": f.evidence,
                    "line_start": f.line_start,
                    "line_end": f.line_end,
                    "scene_path": f.scene_path,
                }
                for f in self.state.findings
            ]
        }

    def get_scene_content(self) -> Optional[str]:
        """Get the scene text content."""
        if not self.state:
            return None
        return self.state.scene_content

    def clear_session(self) -> dict:
        """Clear the current analysis state."""
        if not self.state:
            return {"error": "No active session"}

        # Reset engine state
        self.state = None
        self.results = None
        self.analysis_progress = None
        self._snapshot_id = None

        return {"cleared": True, "message": "Session cleared"}


class ResumeScenePathError(FileNotFoundError):
    """Raised when the saved scene path for a resumable session is invalid.

    Kept as a stub for backward-compatibility with tests.
    Will be fully removed when session_manager.py is deleted.
    """

    def __init__(
        self,
        message: str,
        *,
        saved_scene_path: str = "",
        attempted_scene_path: str = "",
        project_path: str = "",
        override_provided: bool = False,
        saved_scene_paths: Optional[list[str]] = None,
        missing_scene_paths: Optional[list[str]] = None,
    ):
        super().__init__(message)
        self.saved_scene_path = saved_scene_path
        self.attempted_scene_path = attempted_scene_path
        self.project_path = project_path
        self.override_provided = override_provided
        self.saved_scene_paths = saved_scene_paths or ([saved_scene_path] if saved_scene_path else [])
        self.missing_scene_paths = missing_scene_paths or ([attempted_scene_path] if attempted_scene_path else [])
