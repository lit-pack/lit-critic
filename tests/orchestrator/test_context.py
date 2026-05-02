"""Tests for platform discussion context condensation."""

from orchestrator.context import condense_discussion_context


def test_condense_discussion_context_filters_and_truncates():
    turns = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
        {"bad": "entry"},
    ]

    ctx = condense_discussion_context(discussion_turns=turns, max_turns=3)

    assert ctx["turn_count"] == 3
    assert [t["content"] for t in ctx["discussion_turns"]] == ["u2", "a2", "u3"]


def test_condense_discussion_context_handles_none_input():
    ctx = condense_discussion_context(discussion_turns=None)
    assert ctx == {"discussion_turns": [], "turn_count": 0}
