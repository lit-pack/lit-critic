"""Platform orchestration facade that keeps FS/state concerns local."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from contracts.v1.schemas import (
    AnalyzeModelConfig,
    AnalyzeRequest,
    AnalyzeResponse,
    FindingContract,
    IndexesContract,
    ReEvaluateFindingRequest,
    ReEvaluateFindingResponse,
)

from .core_client import CoreClient
from .persistence.database import get_passive_connection
from .services.knowledge_serializer import serialize_all_knowledge


class PlatformFacade:
    """Local orchestration facade that prepares payloads for stateless Core."""

    def __init__(self, *, core_client: CoreClient):
        self.core_client = core_client

    @staticmethod
    def load_scene_text(scene_path: Path) -> str:
        """Load scene text from local filesystem (Platform-owned concern)."""
        return scene_path.read_text(encoding="utf-8")

    @staticmethod
    def load_indexes_from_project(project_path: Path) -> IndexesContract:
        """Load authored + extracted knowledge and convert to v1 indexes contract."""
        payload: dict[str, str | None] = {
            "CANON": None,
            "CAST": None,
            "GLOSSARY": None,
            "STYLE": None,
            "THREADS": None,
            "TIMELINE": None,
        }

        canon_path = project_path / "CANON.md"
        style_path = project_path / "STYLE.md"
        payload["CANON"] = (
            canon_path.read_text(encoding="utf-8") if canon_path.exists() else None
        )
        payload["STYLE"] = (
            style_path.read_text(encoding="utf-8") if style_path.exists() else None
        )

        conn = get_passive_connection(project_path)
        if conn is not None:
            try:
                serialized = serialize_all_knowledge(conn)
            except Exception:  # noqa: BLE001 - keep fallback behavior when DB unavailable
                serialized = {}
            finally:
                conn.close()

            payload["CAST"] = serialized.get("cast")
            payload["GLOSSARY"] = serialized.get("glossary")
            payload["THREADS"] = serialized.get("threads")
            payload["TIMELINE"] = serialized.get("timeline")

        return IndexesContract.model_validate(payload)

    @staticmethod
    def load_legacy_indexes_from_project(
        project_path: Path,
        *,
        optional_filenames: tuple[str, ...] = (),
    ) -> dict[str, str]:
        """Load indexes in legacy ``*.md`` key shape expected by server prompts."""
        contract_indexes = PlatformFacade.load_indexes_from_project(project_path).model_dump()
        # Map contract keys (uppercase, no .md) to index dict keys.
        # CANON and STYLE keep their .md form; the extracted indexes use short keys.
        _contract_to_key = {"CAST": "cast", "GLOSSARY": "glossary",
                             "THREADS": "threads", "TIMELINE": "timeline"}
        indexes = {
            _contract_to_key.get(key, f"{key}.md"): (value or "")
            for key, value in contract_indexes.items()
        }

        for filename in optional_filenames:
            path = project_path / filename
            if path.exists():
                indexes[filename] = path.read_text(encoding="utf-8")

        return indexes

    def analyze_scene_text(
        self,
        *,
        scene_text: str,
        indexes: IndexesContract,
        analysis_model: str,
        api_keys: dict[str, str],
        max_tokens: int,
        learning_context: dict[str, Any] | None = None,
    ) -> AnalyzeResponse:
        """Prepare analyze request and call Core."""
        req = AnalyzeRequest(
            scene_text=scene_text,
            indexes=indexes,
            learning_context=learning_context,
            model_settings=AnalyzeModelConfig(
                analysis_model=analysis_model,
                api_keys=api_keys,
                max_tokens=max_tokens,
            ),
        )
        return self.core_client.analyze(req)

    def re_evaluate_finding(
        self,
        *,
        stale_finding: FindingContract,
        updated_scene_text: str,
        analysis_model: str,
        api_keys: dict[str, str],
        max_tokens: int,
        minimal_context: dict[str, Any] | None = None,
    ) -> ReEvaluateFindingResponse:
        """Prepare re-evaluate payload and call Core."""
        req = ReEvaluateFindingRequest(
            stale_finding=stale_finding,
            updated_scene_text=updated_scene_text,
            minimal_context=minimal_context,
            model_settings=AnalyzeModelConfig(
                analysis_model=analysis_model,
                api_keys=api_keys,
                max_tokens=max_tokens,
            ),
        )
        return self.core_client.re_evaluate(req)
