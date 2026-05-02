"""
Legacy session persistence module — archived in v22.

The ``session`` and ``finding`` tables were dropped in migration v22.  All
functions are now no-ops, re-exported from the snapshot service, or raise
``NotImplementedError``.

Tests that import from this module are marked ``pytestmark = pytest.mark.skip``
and will never execute these stubs.
"""

# Re-exports that live in the new snapshot-only service
from orchestrator.services.session_service import (  # noqa: F401
    check_active_session,
    complete_active_session,
    compute_scene_hash,
    delete_session_by_id,
    get_session_detail,
    list_sessions,
)


# ---------------------------------------------------------------------------
# Dead stubs — interactive-session functions that no longer exist
# ---------------------------------------------------------------------------


def create_session(*args, **kwargs):
    """Removed in v22 — use create_snapshot_from_core_findings()."""
    raise NotImplementedError("Session table removed in v22")


def load_active_session(*args, **kwargs):
    """Removed in v22."""
    return None


def complete_session(*args, **kwargs):
    """Removed in v22."""
    return False


def abandon_session(*args, **kwargs):
    """Removed in v22."""


def abandon_active_session(*args, **kwargs):
    """Removed in v22."""
    return False


def validate_session(*args, **kwargs):
    """Removed in v22."""
    return False, "Session table removed in v22"


def persist_finding(*args, **kwargs):
    """Removed in v22."""


def persist_session_learning(*args, **kwargs):
    """Removed in v22."""


def all_findings_considered(findings):
    """Return True when every finding has a terminal status.

    Inlined from the removed session_state_machine module.
    """
    _TERMINAL = {"accepted", "rejected", "withdrawn"}
    return all((f.status or "pending") in _TERMINAL for f in findings)


async def detect_and_apply_scene_changes(*args, **kwargs):
    """Removed in v22."""
    return None
