"""Tests for orchestrator.persistence.path_utils."""

import sys
from pathlib import Path

import pytest

from orchestrator.persistence.path_utils import to_absolute, to_relative


# ---------------------------------------------------------------------------
# Platform-specific root helpers
# ---------------------------------------------------------------------------

def _root() -> Path:
    """Return a plausible absolute project root for the current platform."""
    if sys.platform == "win32":
        return Path("C:/Projects/mynovel")
    return Path("/home/alice/novel")


def _abs(rel: str) -> str:
    """Build an absolute path string under the project root."""
    return str(_root() / rel)


# ---------------------------------------------------------------------------
# to_relative
# ---------------------------------------------------------------------------

class TestToRelative:
    def test_already_relative_passes_through(self):
        result = to_relative(_root(), "ch01.txt")
        assert result == "ch01.txt"

    def test_already_relative_with_subdir(self):
        result = to_relative(_root(), "scenes/ch01.txt")
        assert result == "scenes/ch01.txt"

    def test_absolute_under_root_is_relativized(self):
        result = to_relative(_root(), _abs("ch01.txt"))
        assert result == "ch01.txt"

    def test_absolute_nested_under_root(self):
        result = to_relative(_root(), _abs("scenes/act1/ch01.txt"))
        assert result == "scenes/act1/ch01.txt"

    def test_absolute_outside_root_left_alone(self):
        outside = str(Path(_abs("ch01.txt")).parent.parent.parent / "other" / "file.txt")
        result = to_relative(_root(), outside)
        assert result == outside

    def test_empty_string_returns_empty(self):
        assert to_relative(_root(), "") == ""

    def test_none_returns_empty(self):
        assert to_relative(_root(), None) == ""

    def test_project_path_none_absolute_left_alone(self):
        abs_path = _abs("ch01.txt")
        result = to_relative(None, abs_path)
        assert result == abs_path

    def test_project_path_none_relative_passes_through(self):
        result = to_relative(None, "ch01.txt")
        assert result == "ch01.txt"

    def test_posix_slashes_on_relative_input(self):
        # Even a Windows-style relative path should come out with POSIX slashes
        result = to_relative(_root(), "scenes/ch01.txt")
        assert "/" in result
        assert "\\" not in result


# ---------------------------------------------------------------------------
# to_absolute
# ---------------------------------------------------------------------------

class TestToAbsolute:
    def test_relative_resolved_under_root(self):
        result = to_absolute(_root(), "ch01.txt")
        assert result == (_root().resolve() / "ch01.txt").resolve()

    def test_nested_relative(self):
        result = to_absolute(_root(), "scenes/act1/ch01.txt")
        assert result == (_root().resolve() / "scenes/act1/ch01.txt").resolve()

    def test_already_absolute_returned_as_path(self):
        abs_path = _abs("ch01.txt")
        result = to_absolute(_root(), abs_path)
        assert result == Path(abs_path)

    def test_empty_string_returns_none(self):
        assert to_absolute(_root(), "") is None

    def test_none_returns_none(self):
        assert to_absolute(_root(), None) is None

    def test_project_path_none_relative_returns_path(self):
        result = to_absolute(None, "ch01.txt")
        assert result == Path("ch01.txt")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_abs_rel_abs_is_identity(self):
        original = _abs("scenes/ch01.txt")
        rel = to_relative(_root(), original)
        restored = to_absolute(_root(), rel)
        assert restored == Path(original).resolve()

    def test_rel_abs_rel_is_identity(self):
        original = "scenes/ch01.txt"
        abs_path = to_absolute(_root(), original)
        rel = to_relative(_root(), str(abs_path))
        assert rel == original
