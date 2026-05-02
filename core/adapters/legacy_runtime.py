"""Temporary adapter that bridges Core ports to legacy ``server.*`` runtime."""

from __future__ import annotations

import re

from core.domain import CoreFinding
from core.ports import AnalysisEnginePort, DiscussionEnginePort, ReEvaluationEnginePort
from orchestrator.runtime.api import re_evaluate_finding, run_analysis
from orchestrator.runtime.models import Finding
from orchestrator.runtime.prompts import build_discussion_messages, get_discussion_system_prompt


class LegacyAnalysisEngineAdapter(AnalysisEnginePort):
    """Bridge analysis port to legacy ``server.api.run_analysis``."""

    async def analyze(
        self,
        *,
        client,
        scene_text: str,
        indexes: dict[str, str],
        model: str,
        max_tokens: int,
    ) -> dict:
        return await run_analysis(
            client,
            scene_text,
            indexes,
            model=model,
            max_tokens=max_tokens,
        )


class LegacyDiscussionEngineAdapter(DiscussionEnginePort):
    """Minimal discussion adapter — one-shot LLM call for explain_finding.

    Previously delegated to ``orchestrator.runtime.discussion.handle_discussion``
    which carried side-effects (discussion turns, learning, state-machine
    transitions).  The only active caller is ``explain_finding`` in
    ``core.service`` which needs none of those — just the prompt + LLM call +
    display-text extraction.
    """

    # Status tags that may appear in the LLM response.
    _STATUS_TAGS = (
        "[ESCALATED]", "[REVISED]", "[WITHDRAWN]",
        "[REJECTED]", "[ACCEPTED]", "[CONCEDED]", "[CONTINUE]",
    )

    async def discuss(
        self,
        *,
        discussion_client,
        scene_text: str,
        finding: CoreFinding,
        author_message: str,
        model: str,
        max_tokens: int,
    ) -> tuple[str, str, CoreFinding]:
        # Build prompt context — CoreFinding exposes the same attributes the
        # prompt helpers expect (number, severity, lens, location, …).
        system_prompt = get_discussion_system_prompt(
            finding, scene_text, prior_outcomes="",
        )
        messages = build_discussion_messages(finding, author_message)

        try:
            response = await discussion_client.create_message(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                system=system_prompt,
            )
            raw_text: str = response.text
        except Exception as exc:
            return f"[Discussion error: {exc}]", "continue", finding

        display_text, status = self._parse_display_text(raw_text)
        return display_text, status, finding

    # ------------------------------------------------------------------
    # Minimal response parser — extracts display text and status only.
    # No revision/preference/ambiguity/learning handling.
    # ------------------------------------------------------------------

    @classmethod
    def _parse_display_text(cls, raw: str) -> tuple[str, str]:
        """Strip metadata tags and return ``(display_text, status)``."""
        text = raw

        # Remove [REVISION]…[/REVISION] blocks.
        text = re.sub(r"\[REVISION\].*?\[/REVISION\]", "", text, flags=re.DOTALL)

        # Remove [PREFERENCE: …] tags.
        text = re.sub(r"\[PREFERENCE:\s*.*?\]", "", text)

        # Remove [AMBIGUITY:…] tags.
        text = re.sub(r"\[AMBIGUITY:\w+\]", "", text)

        # Extract status from the first matching tag.
        status = "continue"
        for tag in cls._STATUS_TAGS:
            if tag in text:
                status = tag.strip("[]").lower()
                text = text.replace(tag, "", 1)
                break

        return text.strip(), status


class LegacyReEvaluationEngineAdapter(ReEvaluationEnginePort):
    """Bridge re-evaluation port to legacy ``server.api.re_evaluate_finding``."""

    async def re_evaluate(
        self,
        *,
        client,
        finding: CoreFinding,
        updated_scene_text: str,
        model: str,
        max_tokens: int,
    ) -> dict:
        legacy_finding = Finding.from_dict(finding.to_dict(include_state=True))
        return await re_evaluate_finding(
            client,
            legacy_finding,
            updated_scene_text,
            model=model,
            max_tokens=max_tokens,
        )
