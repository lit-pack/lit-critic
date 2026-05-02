"""
Helpers for converting between absolute and project-relative path strings.

All stored paths in the DB are POSIX-style relative strings.
These helpers are the single conversion point used by stores and migrations.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


def to_relative(project_path: Path | str | None, path_str: str | None) -> str:
    """Convert *path_str* to a POSIX-style path relative to *project_path*.

    Rules:
    - ``None`` or empty string → returns ``""``
    - Already relative → returned as-is (converted to POSIX slashes)
    - Absolute and under *project_path* → relativized, POSIX slashes
    - Absolute but outside *project_path* → returned unchanged (safety)
    """
    if not path_str:
        return path_str if path_str is not None else ""

    p = Path(path_str)

    if not p.is_absolute():
        # Already relative — normalise to POSIX slashes
        return PurePosixPath(p).as_posix()

    if project_path is None:
        return path_str

    root = Path(project_path).resolve()
    try:
        rel = p.resolve().relative_to(root)
        return PurePosixPath(rel).as_posix()
    except ValueError:
        # Outside project root — leave unchanged
        return path_str


def to_absolute(project_path: Path | str | None, path_str: str | None) -> Path | None:
    """Convert *path_str* (relative or absolute) to an absolute ``Path``.

    Rules:
    - ``None`` or empty string → returns ``None``
    - Already absolute → returned as ``Path(path_str)``
    - Relative → joined with *project_path* and resolved
    - If *project_path* is ``None`` and path is relative → returned as ``Path(path_str)``
    """
    if not path_str:
        return None

    p = Path(path_str)

    if p.is_absolute():
        return p

    if project_path is None:
        return p

    return (Path(project_path).resolve() / p).resolve()
