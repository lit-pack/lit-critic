"""Discussion-context condensation helpers for Platform -> Core calls."""

from __future__ import annotations

from typing import Any


def condense_discussion_context(
    *,
    discussion_turns: list[dict[str, Any]] | None,
    max_turns: int = 8,
) -> dict[str, Any]:
    """Condense discussion history into a Core-friendly payload.

    Keeps only valid ``{"role", "content"}`` turns and truncates to the most
    recent ``max_turns`` turns.
    """
    turns = discussion_turns or []
    filtered = [
        {"role": t["role"], "content": t["content"]}
        for t in turns
        if isinstance(t, dict)
        and isinstance(t.get("role"), str)
        and isinstance(t.get("content"), str)
    ]
    if max_turns > 0:
        filtered = filtered[-max_turns:]

    return {
        "discussion_turns": filtered,
        "turn_count": len(filtered),
    }
