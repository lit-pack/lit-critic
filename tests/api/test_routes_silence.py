"""Integration tests for web.routes_silence — silence rule CRUD API (Task C4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_category_rule(client, project_path: str, lens: str = "prose") -> dict:
    """POST a category rule and return the response JSON."""
    resp = client.post(
        "/api/silence-rules",
        params={"project_path": project_path},
        json={
            "rule_type": "category",
            "scope": "project",
            "lens": lens,
            "created_at": "2026-04-13T10:00:00",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_instance_rule(client, project_path: str, scene_path: str = "text/ch1.md", finding_id: int = 1) -> dict:
    resp = client.post(
        "/api/silence-rules",
        params={"project_path": project_path},
        json={
            "rule_type": "instance",
            "scope": "scene",
            "scene_path": scene_path,
            "finding_id": finding_id,
            "created_at": "2026-04-13T10:00:00",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/silence-rules
# ---------------------------------------------------------------------------

def test_create_instance_rule(client, tmp_path):
    data = _create_instance_rule(client, str(tmp_path))
    assert data["id"] is not None
    assert data["rule_type"] == "instance"
    assert data["scope"] == "scene"
    assert data["finding_id"] == 1
    assert data["suspended"] is False


def test_create_pattern_rule(client, tmp_path):
    resp = client.post(
        "/api/silence-rules",
        params={"project_path": str(tmp_path)},
        json={
            "rule_type": "pattern",
            "scope": "scene",
            "scene_path": "text/ch1.md",
            "lens": "prose",
            "text_pattern": "too long",
            "note": "dialect is intentional",
            "created_at": "2026-04-13T10:00:00",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["rule_type"] == "pattern"
    assert data["text_pattern"] == "too long"
    assert data["note"] == "dialect is intentional"


def test_create_category_rule(client, tmp_path):
    data = _create_category_rule(client, str(tmp_path))
    assert data["rule_type"] == "category"
    assert data["scope"] == "project"
    assert data["lens"] == "prose"


def test_create_rule_project_not_found(client, tmp_path):
    resp = client.post(
        "/api/silence-rules",
        params={"project_path": str(tmp_path / "missing")},
        json={"rule_type": "category", "scope": "project", "lens": "prose", "created_at": "ts"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/silence-rules
# ---------------------------------------------------------------------------

def test_list_all_rules(client, tmp_path):
    _create_instance_rule(client, str(tmp_path))
    _create_category_rule(client, str(tmp_path))

    resp = client.get("/api/silence-rules", params={"project_path": str(tmp_path)})
    assert resp.status_code == 200
    rules = resp.json()
    assert len(rules) == 2


def test_list_empty(client, tmp_path):
    resp = client.get("/api/silence-rules", params={"project_path": str(tmp_path)})
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_applicable_rules_for_scene(client, tmp_path):
    _create_instance_rule(client, str(tmp_path), scene_path="text/ch1.md")
    _create_instance_rule(client, str(tmp_path), scene_path="text/ch2.md", finding_id=2)
    _create_category_rule(client, str(tmp_path))  # project-wide

    resp = client.get(
        "/api/silence-rules",
        params={"project_path": str(tmp_path), "scene_path": "text/ch1.md"},
    )
    assert resp.status_code == 200
    rules = resp.json()
    # Should return ch1 instance + project-wide category, NOT ch2 instance.
    assert len(rules) == 2
    rule_types = {r["rule_type"] for r in rules}
    assert "instance" in rule_types
    assert "category" in rule_types


def test_list_rules_project_not_found(client, tmp_path):
    resp = client.get("/api/silence-rules", params={"project_path": str(tmp_path / "missing")})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/silence-rules/{rule_id}
# ---------------------------------------------------------------------------

def test_patch_suspend_rule(client, tmp_path):
    data = _create_instance_rule(client, str(tmp_path))
    rule_id = data["id"]

    resp = client.patch(
        f"/api/silence-rules/{rule_id}",
        params={"project_path": str(tmp_path)},
        json={"suspended": True, "suspended_at": "2026-04-14T00:00:00"},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["suspended"] is True
    assert updated["suspended_at"] == "2026-04-14T00:00:00"


def test_patch_unsuspend_rule(client, tmp_path):
    data = _create_instance_rule(client, str(tmp_path))
    rule_id = data["id"]

    # First suspend.
    client.patch(
        f"/api/silence-rules/{rule_id}",
        params={"project_path": str(tmp_path)},
        json={"suspended": True, "suspended_at": "2026-04-14T00:00:00"},
    )
    # Then unsuspend.
    resp = client.patch(
        f"/api/silence-rules/{rule_id}",
        params={"project_path": str(tmp_path)},
        json={"suspended": False},
    )
    assert resp.status_code == 200
    assert resp.json()["suspended"] is False


def test_patch_rule_not_found(client, tmp_path):
    resp = client.patch(
        "/api/silence-rules/99999",
        params={"project_path": str(tmp_path)},
        json={"suspended": True},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/silence-rules/{rule_id}
# ---------------------------------------------------------------------------

def test_delete_rule(client, tmp_path):
    data = _create_instance_rule(client, str(tmp_path))
    rule_id = data["id"]

    resp = client.delete(
        f"/api/silence-rules/{rule_id}",
        params={"project_path": str(tmp_path)},
    )
    assert resp.status_code == 204

    # Rule should no longer appear in list.
    list_resp = client.get("/api/silence-rules", params={"project_path": str(tmp_path)})
    assert list_resp.json() == []


def test_delete_rule_not_found(client, tmp_path):
    resp = client.delete(
        "/api/silence-rules/99999",
        params={"project_path": str(tmp_path)},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Full CRUD cycle
# ---------------------------------------------------------------------------

def test_full_crud_cycle(client, tmp_path):
    """Create → list → patch → delete."""
    # Create
    created = _create_category_rule(client, str(tmp_path), lens="pacing")
    rule_id = created["id"]
    assert created["lens"] == "pacing"

    # List — 1 rule
    rules = client.get("/api/silence-rules", params={"project_path": str(tmp_path)}).json()
    assert len(rules) == 1

    # Patch — suspend
    patched = client.patch(
        f"/api/silence-rules/{rule_id}",
        params={"project_path": str(tmp_path)},
        json={"suspended": True, "suspended_at": "2026-04-14T00:00:00"},
    ).json()
    assert patched["suspended"] is True

    # List with include_suspended=False — should be empty
    active_rules = client.get(
        "/api/silence-rules",
        params={"project_path": str(tmp_path), "include_suspended": False},
    ).json()
    assert active_rules == []

    # Delete
    resp = client.delete(
        f"/api/silence-rules/{rule_id}",
        params={"project_path": str(tmp_path)},
    )
    assert resp.status_code == 204

    # List — empty
    final_rules = client.get("/api/silence-rules", params={"project_path": str(tmp_path)}).json()
    assert final_rules == []
