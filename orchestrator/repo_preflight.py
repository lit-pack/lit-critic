"""Repo-path preflight validation shared by Python clients.

This module implements the canonical validation contract for a lit-critic
installation directory (repo path).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MARKER_FILENAME = "lit-critic-server.py"


@dataclass(frozen=True)
class RepoPathValidationResult:
    ok: bool
    reason_code: str
    message: str
    path: str | None = None


def validate_repo_path(raw_path: str | None) -> RepoPathValidationResult:
    """Validate a repository path using the canonical rule set."""
    candidate = (raw_path or "").strip()
    if not candidate:
        return RepoPathValidationResult(
            ok=False,
            reason_code="empty",
            message="Repository path is empty.",
            path=None,
        )

    try:
        normalized = str(Path(candidate).expanduser().resolve())
        p = Path(normalized)
    except Exception as exc:  # pragma: no cover - defensive path normalization guard
        return RepoPathValidationResult(
            ok=False,
            reason_code="unknown_error",
            message=f"Could not normalize repository path: {exc}",
            path=candidate,
        )

    try:
        if not p.exists():
            return RepoPathValidationResult(
                ok=False,
                reason_code="not_found",
                message=(
                    f"Repository path was not found: {normalized}. "
                    f"Choose a directory containing {MARKER_FILENAME}."
                ),
                path=normalized,
            )

        if not p.is_dir():
            return RepoPathValidationResult(
                ok=False,
                reason_code="not_directory",
                message=(
                    f"Repository path is not a directory: {normalized}. "
                    f"Choose a directory containing {MARKER_FILENAME}."
                ),
                path=normalized,
            )

        marker_path = p / MARKER_FILENAME
        if not marker_path.exists():
            return RepoPathValidationResult(
                ok=False,
                reason_code="missing_marker",
                message=(
                    f"Repository directory does not contain {MARKER_FILENAME}: {normalized}."
                ),
                path=normalized,
            )

        return RepoPathValidationResult(
            ok=True,
            reason_code="",
            message="Repository path is valid.",
            path=normalized,
        )
    except Exception as exc:  # pragma: no cover - defensive filesystem guard
        return RepoPathValidationResult(
            ok=False,
            reason_code="unknown_error",
            message=f"Unexpected error while validating repository path: {exc}",
            path=normalized,
        )
