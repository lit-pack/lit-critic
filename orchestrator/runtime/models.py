"""
Data structures and exceptions for the lit-critic system.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLMClient

from .config import DEFAULT_MODEL, AVAILABLE_MODELS


class CoordinatorError(Exception):
    """Raised when the coordinator fails to produce valid output after all retries."""

    def __init__(self, message: str, raw_output: str = "", attempts: int = 0):
        super().__init__(message)
        self.raw_output = raw_output
        self.attempts = attempts


class AllLensesFailedError(Exception):
    """Raised by run_analysis when all lenses fail, allowing callers to distinguish
    network/connectivity failures from structural errors."""

    def __init__(self, message: str, is_transient: bool = False):
        super().__init__(message)
        self.is_transient = is_transient


@dataclass
class LearningData:
    """Tracks learning during a session."""
    project_name: str = "Unknown"
    review_count: int = 0
    preferences: list[dict] = field(default_factory=list)      # Findings rejected as non-problems
    blind_spots: list[dict] = field(default_factory=list)      # Recurring issues author accepts
    resolutions: list[dict] = field(default_factory=list)      # How author typically fixes things
    ambiguity_intentional: list[dict] = field(default_factory=list)
    ambiguity_accidental: list[dict] = field(default_factory=list)
    
    editorial_profile: str | None = None

    # Session tracking
    session_rejections: list[dict] = field(default_factory=list)
    session_acceptances: list[dict] = field(default_factory=list)
    session_ambiguity_answers: list[dict] = field(default_factory=list)


@dataclass
class Finding:
    """A single editorial finding."""
    number: int
    severity: str  # critical, major, minor
    lens: str      # prose, structure, logic, clarity, continuity
    location: str
    line_start: Optional[int] = None   # First line of the issue (1-based), from lens output
    line_end: Optional[int] = None     # Last line of the issue (1-based), from lens output
    scene_path: Optional[str] = None   # Source scene file path (for multi-scene sessions)
    evidence: str = ""
    impact: str = ""
    options: list[str] = field(default_factory=list)
    flagged_by: list[str] = field(default_factory=list)
    ambiguity_type: Optional[str] = None
    stale: bool = False                # True when the finding's text region was edited by the author
    origin: str = "legacy"             # "code", "checker", "critic", or "legacy" (pre-tiering)
    
    # Discussion state (partial — author_response, revision_history, outcome_reason removed in F2a)
    status: str = "pending"  # pending, accepted, rejected, revised, withdrawn, escalated, discussed
    discussion_turns: list[dict] = field(default_factory=list)   # [{role: "user"/"assistant", content: "..."}]

    def to_dict(self, include_state: bool = False) -> dict:
        """Convert finding to dictionary. If include_state=True, includes discussion state."""
        result = {
            "number": self.number,
            "severity": self.severity,
            "lens": self.lens,
            "location": self.location,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "scene_path": self.scene_path,
            "evidence": self.evidence,
            "impact": self.impact,
            "options": self.options,
            "flagged_by": self.flagged_by,
            "ambiguity_type": self.ambiguity_type,
            "stale": self.stale,
            "origin": self.origin,
        }
        if include_state:
            result["status"] = self.status
            result["discussion_turns"] = self.discussion_turns
        return result
    
    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        """Create Finding from dictionary."""
        finding = cls(
            number=data.get("number", 0),
            severity=data.get("severity", "minor"),
            lens=data.get("lens", "unknown"),
            location=data.get("location", ""),
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            scene_path=data.get("scene_path"),
            evidence=data.get("evidence", ""),
            impact=data.get("impact", ""),
            options=data.get("options", []),
            flagged_by=data.get("flagged_by", []),
            ambiguity_type=data.get("ambiguity_type"),
            stale=data.get("stale", False),
            origin=data.get("origin", "legacy"),
        )
        finding.status = data.get("status", "pending")
        finding.discussion_turns = data.get("discussion_turns", [])
        return finding


@dataclass
class LensResult:
    """Output from a single lens analysis."""
    lens_name: str
    findings: list[dict]
    raw_output: str
    error: Optional[str] = None
    is_transient: bool = False


@dataclass 
class SessionState:
    """Runtime workspace for an analysis pass.

    Holds the LLM client, scene content, indexes, learning data and model
    configuration for one analysis run.  DB persistence fields (db_conn,
    session_id) were removed in v22 — results are now written as
    ``AnalysisSnapshot`` records via ``create_snapshot_from_core_findings()``.

    Dual-LLM support: The ``discussion_model`` and ``discussion_client`` fields
    allow using a different (typically cheaper/faster) model for discussion
    than for analysis. When ``discussion_model`` is ``None``, the analysis
    model/client is used for both.
    """
    client: "LLMClient"
    scene_content: str
    scene_path: str
    project_path: Path
    indexes: dict[str, str]
    scene_paths: list[str] = field(default_factory=list)
    scene_line_map: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    glossary_issues: list[str] = field(default_factory=list)
    learning: LearningData = field(default_factory=LearningData)
    depth_mode: str = "deep"
    frontier_model: Optional[str] = None
    checker_model: Optional[str] = None
    model: str = field(default_factory=lambda: DEFAULT_MODEL)
    discussion_model: Optional[str] = None  # None = use analysis model
    discussion_client: Optional["LLMClient"] = None  # None = use analysis client
    index_context_hash: str = ""
    index_context_stale: bool = False
    index_rerun_prompted: bool = False
    index_changed_files: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Canonical tier assignments (Phase 3) with legacy compatibility:
        # - checker_model falls back to legacy analysis model
        # - frontier_model falls back to legacy discussion/analysis model
        self.checker_model = self.checker_model or self.model
        self.frontier_model = self.frontier_model or self.discussion_model or self.model

        if not self.depth_mode:
            self.depth_mode = "deep"

        # Keep legacy fields readable and aligned for transitional callers.
        self.model = self.checker_model
        self.discussion_model = self.frontier_model

    @property
    def effective_checker_model(self) -> str:
        """Canonical checker-tier model, with legacy fallback safety."""
        return self.checker_model or self.model

    @property
    def effective_frontier_model(self) -> str:
        """Canonical frontier-tier model, with legacy fallback safety."""
        return self.frontier_model or self.discussion_model or self.model

    @property
    def model_id(self) -> str:
        """Full API model identifier (e.g. 'claude-sonnet-4-5-20250929' or 'gpt-4o')."""
        return AVAILABLE_MODELS[self.effective_checker_model]["id"]

    @property
    def model_provider(self) -> str:
        """Provider name (e.g. 'anthropic' or 'openai')."""
        return AVAILABLE_MODELS[self.effective_checker_model]["provider"]

    @property
    def model_max_tokens(self) -> int:
        """Max tokens for the selected model."""
        return AVAILABLE_MODELS[self.effective_checker_model]["max_tokens"]

    @property
    def model_label(self) -> str:
        """Human-readable label for the selected model."""
        return AVAILABLE_MODELS[self.effective_checker_model]["label"]

    @property
    def discussion_model_id(self) -> str:
        """Full API model identifier for discussion (falls back to analysis model if not set)."""
        model = self.effective_frontier_model
        return AVAILABLE_MODELS[model]["id"]

    @property
    def discussion_model_provider(self) -> str:
        """Provider name for discussion model (falls back to analysis model if not set)."""
        model = self.effective_frontier_model
        return AVAILABLE_MODELS[model]["provider"]

    @property
    def discussion_model_label(self) -> str:
        """Human-readable label for discussion model (falls back to analysis model if not set)."""
        model = self.effective_frontier_model
        return AVAILABLE_MODELS[model]["label"]

    @property
    def effective_discussion_client(self) -> "LLMClient":
        """The LLM client to use for discussion (falls back to analysis client if not set)."""
        return self.discussion_client or self.client
