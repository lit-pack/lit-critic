from pathlib import Path

from orchestrator.repo_preflight import MARKER_FILENAME, validate_repo_path


def test_validate_repo_path_empty():
    result = validate_repo_path("")
    assert result.ok is False
    assert result.reason_code == "empty"


def test_validate_repo_path_not_found(tmp_path: Path):
    missing = tmp_path / "missing"
    result = validate_repo_path(str(missing))
    assert result.ok is False
    assert result.reason_code == "not_found"


def test_validate_repo_path_not_directory(tmp_path: Path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    result = validate_repo_path(str(file_path))
    assert result.ok is False
    assert result.reason_code == "not_directory"


def test_validate_repo_path_missing_marker(tmp_path: Path):
    result = validate_repo_path(str(tmp_path))
    assert result.ok is False
    assert result.reason_code == "missing_marker"


def test_validate_repo_path_ok(tmp_path: Path):
    marker = tmp_path / MARKER_FILENAME
    marker.write_text("print('ok')", encoding="utf-8")
    result = validate_repo_path(str(tmp_path))
    assert result.ok is True
    assert result.reason_code == ""
    assert result.path == str(tmp_path.resolve())
