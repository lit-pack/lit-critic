"""Core-native domain models used by stateless orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CoreFinding:
    """Core-native finding shape independent of legacy runtime types."""

    number: int
    severity: str
    lens: str
    location: str
    line_start: int | None = None
    line_end: int | None = None
    evidence: str = ""
    impact: str = ""
    options: list[str] = field(default_factory=list)
    flagged_by: list[str] = field(default_factory=list)
    ambiguity_type: str | None = None
    stale: bool = False
    status: str = "pending"
    discussion_turns: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoreFinding":
        return cls(
            number=data.get("number", 0),
            severity=data.get("severity", "minor"),
            lens=data.get("lens", "unknown"),
            location=data.get("location", ""),
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            evidence=data.get("evidence", ""),
            impact=data.get("impact", ""),
            options=list(data.get("options", [])),
            flagged_by=list(data.get("flagged_by", [])),
            ambiguity_type=data.get("ambiguity_type"),
            stale=bool(data.get("stale", False)),
            status=data.get("status", "pending"),
            discussion_turns=list(data.get("discussion_turns", [])),
        )

    def to_dict(self, *, include_state: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "number": self.number,
            "severity": self.severity,
            "lens": self.lens,
            "location": self.location,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "evidence": self.evidence,
            "impact": self.impact,
            "options": self.options,
            "flagged_by": self.flagged_by,
            "ambiguity_type": self.ambiguity_type,
            "stale": self.stale,
        }
        if include_state:
            payload.update(
                {
                    "status": self.status,
                    "discussion_turns": self.discussion_turns,
                }
            )
        return payload


# ---------------------------------------------------------------------------
# Read-only feedback model — AnalysisSnapshot and SnapshotFinding
# ---------------------------------------------------------------------------

#: Valid states for a SnapshotFinding.
FINDING_STATES = frozenset({"active", "silenced", "resolved"})


@dataclass(slots=True)
class SnapshotFinding:
    """A single finding from an ``AnalysisSnapshot``.

    States:
    - ``active``   — visible to the author as an annotation.
    - ``silenced`` — hidden by a silence rule; stored for learning.
    - ``resolved`` — text changed and this finding no longer applies.
    """

    # DB primary key; None until persisted.
    id: int | None = None
    snapshot_id: int | None = None

    number: int = 0
    severity: str = "minor"
    lens: str = "unknown"
    location: str = ""
    line_start: int | None = None
    line_end: int | None = None
    scene_path: str = ""
    evidence: str = ""
    impact: str = ""
    options: list[str] = field(default_factory=list)
    flagged_by: list[str] = field(default_factory=list)
    ambiguity_type: str | None = None

    #: One of "active" | "silenced" | "resolved".
    state: str = "active"

    #: Stable key used to correlate findings across analysis runs.
    #: Derived from (scene_path, lens, line_start, evidence[:80]).
    correlation_key: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SnapshotFinding":
        return cls(
            id=data.get("id"),
            snapshot_id=data.get("snapshot_id"),
            number=data.get("number", 0),
            severity=data.get("severity", "minor"),
            lens=data.get("lens", "unknown"),
            location=data.get("location", ""),
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            scene_path=data.get("scene_path", ""),
            evidence=data.get("evidence", ""),
            impact=data.get("impact", ""),
            options=list(data.get("options", [])),
            flagged_by=list(data.get("flagged_by", [])),
            ambiguity_type=data.get("ambiguity_type"),
            state=data.get("state", "active"),
            correlation_key=data.get("correlation_key", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "snapshot_id": self.snapshot_id,
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
            "state": self.state,
            "correlation_key": self.correlation_key,
        }

    @staticmethod
    def build_correlation_key(
        scene_path: str,
        lens: str,
        line_start: int | None,
        evidence: str,
    ) -> str:
        """Return a stable key for matching this finding across analysis runs."""
        loc = str(line_start) if line_start is not None else ""
        ev = evidence[:80]
        raw = f"{scene_path}|{lens}|{loc}|{ev}"
        # Use a simple hash — no crypto needed, just stable identity.
        return str(hash(raw) & 0xFFFFFFFFFFFFFFFF)


@dataclass(slots=True)
class AnalysisSnapshot:
    """The result of one analysis run — a lightweight, read-only set of findings.

    Replaces the old stateful ``Session`` model.  There is no accept/reject
    workflow and no discussion history.  Findings are displayed as annotations;
    the author silences or edits the underlying text to dismiss them.
    """

    # DB primary key; None until persisted.
    id: int | None = None

    #: Project-relative paths of the analysed scenes.
    scene_paths: list[str] = field(default_factory=list)

    #: "quick" or "deep".
    depth_mode: str = "quick"

    #: Model slots used during this run.
    frontier_model: str = ""
    checker_model: str = ""
    quick_model: str = ""

    #: Per-scene content hashes at analysis time, keyed by relative scene path.
    scene_hashes: dict[str, str] = field(default_factory=dict)

    #: MD5 of the primary scene file at analysis time (single-scene shortcut).
    source_file_hash: str = ""

    #: Hash of the index context used during this run.
    index_context_hash: str = ""

    #: ISO-8601 creation timestamp.
    created_at: str = ""

    #: Findings; empty list when not yet loaded from DB.
    findings: list[SnapshotFinding] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisSnapshot":
        raw_findings = data.get("findings", [])
        return cls(
            id=data.get("id"),
            scene_paths=list(data.get("scene_paths", [])),
            depth_mode=data.get("depth_mode", "quick"),
            frontier_model=data.get("frontier_model", ""),
            checker_model=data.get("checker_model", ""),
            quick_model=data.get("quick_model", ""),
            scene_hashes=dict(data.get("scene_hashes", {})),
            source_file_hash=data.get("source_file_hash", ""),
            index_context_hash=data.get("index_context_hash", ""),
            created_at=data.get("created_at", ""),
            findings=[SnapshotFinding.from_dict(f) for f in raw_findings],
        )

    def to_dict(self, *, include_findings: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "scene_paths": self.scene_paths,
            "depth_mode": self.depth_mode,
            "frontier_model": self.frontier_model,
            "checker_model": self.checker_model,
            "quick_model": self.quick_model,
            "scene_hashes": self.scene_hashes,
            "source_file_hash": self.source_file_hash,
            "index_context_hash": self.index_context_hash,
            "created_at": self.created_at,
        }
        if include_findings:
            payload["findings"] = [f.to_dict() for f in self.findings]
        return payload

    @property
    def active_findings(self) -> list[SnapshotFinding]:
        """Return findings whose state is 'active'."""
        return [f for f in self.findings if f.state == "active"]


# ---------------------------------------------------------------------------
# Silence rules
# ---------------------------------------------------------------------------

#: Valid silence rule types.
SILENCE_RULE_TYPES = frozenset({"instance", "pattern", "category"})

#: Valid silence rule scopes.
SILENCE_RULE_SCOPES = frozenset({"scene", "project"})


@dataclass(slots=True)
class SilenceRule:
    """A persistent rule that suppresses matching ``SnapshotFinding`` objects.

    Types
    -----
    - ``instance``  — silences one specific finding by ``finding_id``.
    - ``pattern``   — silences findings matching ``lens`` + optional
                      ``severity`` + optional ``text_pattern`` substring.
    - ``category``  — silences all findings for a ``lens``; always
                      project-wide (scope is forced to ``"project"``).

    Scope
    -----
    - ``scene``   — applies only to ``scene_path`` (the default).
    - ``project`` — applies across all scenes; required for ``category``.
    """

    id: int | None = None

    #: One of "instance" | "pattern" | "category".
    rule_type: str = "instance"

    #: One of "scene" | "project".
    scope: str = "scene"

    #: Project-relative path of the scene; empty for project-scope rules.
    scene_path: str = ""

    # ---- Targeting (field usage depends on rule_type) ----

    #: DB id of the silenced finding — used by "instance" rules only.
    finding_id: int | None = None

    #: Lens name — used by "pattern" and "category" rules.
    lens: str = ""

    #: Severity filter — used by "pattern" rules; empty means all severities.
    severity: str = ""

    #: Optional substring match against finding evidence/location.
    text_pattern: str = ""

    # ---- Metadata ----

    #: Optional author note explaining why this rule was created.
    note: str = ""

    #: If True, rule is temporarily inactive (can be reactivated).
    suspended: bool = False

    #: ISO-8601 creation timestamp.
    created_at: str = ""

    #: ISO-8601 timestamp when the rule was suspended; empty if not suspended.
    suspended_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SilenceRule":
        return cls(
            id=data.get("id"),
            rule_type=data.get("rule_type", "instance"),
            scope=data.get("scope", "scene"),
            scene_path=data.get("scene_path", ""),
            finding_id=data.get("finding_id"),
            lens=data.get("lens", ""),
            severity=data.get("severity", ""),
            text_pattern=data.get("text_pattern", ""),
            note=data.get("note", ""),
            suspended=bool(data.get("suspended", False)),
            created_at=data.get("created_at", ""),
            suspended_at=data.get("suspended_at", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule_type": self.rule_type,
            "scope": self.scope,
            "scene_path": self.scene_path,
            "finding_id": self.finding_id,
            "lens": self.lens,
            "severity": self.severity,
            "text_pattern": self.text_pattern,
            "note": self.note,
            "suspended": self.suspended,
            "created_at": self.created_at,
            "suspended_at": self.suspended_at,
        }

    def matches(self, finding: SnapshotFinding) -> bool:
        """Return True if this rule applies to *finding*.

        Does **not** check scope or scene_path — that must be done by the
        caller after retrieving the applicable rules for the context.
        Does **not** check ``suspended`` — caller must filter suspended rules
        before calling this.
        """
        if self.rule_type == "instance":
            return self.finding_id is not None and self.finding_id == finding.id

        if self.rule_type == "category":
            return self.lens == finding.lens

        if self.rule_type == "pattern":
            if self.lens and self.lens != finding.lens:
                return False
            if self.severity and self.severity != finding.severity:
                return False
            if self.text_pattern:
                haystack = f"{finding.evidence} {finding.location}".lower()
                if self.text_pattern.lower() not in haystack:
                    return False
            return True

        return False
