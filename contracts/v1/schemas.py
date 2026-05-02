"""Pydantic contracts for the v1 stateless core API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    """Base model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class IndexesContract(_StrictModel):
    CANON: str | None = None
    CAST: str | None = None
    GLOSSARY: str | None = None
    STYLE: str | None = None
    THREADS: str | None = None
    TIMELINE: str | None = None


class MetaContract(_StrictModel):
    model_used: str
    timings: dict[str, float] | None = None
    token_usage: dict[str, int | float] | None = None


class FindingContract(_StrictModel):
    number: int = Field(ge=1)
    severity: Literal["critical", "major", "minor"]
    lens: str
    location: str
    line_start: int | None = None
    line_end: int | None = None
    scene_path: str | None = None
    evidence: str
    impact: str
    options: list[str] = Field(default_factory=list)
    flagged_by: list[str] = Field(default_factory=list)
    ambiguity_type: str | None = None
    stale: bool = False
    origin: Literal["code", "checker", "critic", "legacy"] = "legacy"


class AnalyzeModelConfig(_StrictModel):
    analysis_model: str
    api_keys: dict[str, str] = Field(default_factory=dict)
    max_tokens: int = Field(gt=0)
    provider_options: dict[str, Any] | None = None


class AnalyzeRequest(_StrictModel):
    scene_text: str = Field(min_length=1)
    indexes: IndexesContract
    learning_context: dict[str, Any] | None = None
    model_settings: AnalyzeModelConfig = Field(alias="model_config")


class AnalyzeResponse(_StrictModel):
    findings: list[FindingContract]
    glossary_issues: list[str] = Field(default_factory=list)
    meta: MetaContract


class DiscussModelConfig(_StrictModel):
    discussion_model: str
    api_keys: dict[str, str] = Field(default_factory=dict)
    max_tokens: int = Field(gt=0)
    provider_options: dict[str, Any] | None = None


class DiscussRequest(_StrictModel):
    scene_text: str = Field(min_length=1)
    finding: FindingContract
    discussion_context: dict[str, Any]
    author_message: str = Field(min_length=1)
    model_settings: DiscussModelConfig = Field(alias="model_config")


class DiscussAction(_StrictModel):
    type: Literal["defend", "withdraw", "revise", "escalate", "extract_preference"]
    payload: dict[str, Any] | None = None


class DiscussResponse(_StrictModel):
    assistant_response: str
    action: DiscussAction
    updated_finding: FindingContract | None = None
    extracted_preference: dict[str, Any] | None = None
    meta: MetaContract


class ReEvaluateFindingRequest(_StrictModel):
    stale_finding: FindingContract
    updated_scene_text: str = Field(min_length=1)
    minimal_context: dict[str, Any] | None = None
    model_settings: AnalyzeModelConfig = Field(alias="model_config")


class ReEvaluateFindingResponse(_StrictModel):
    status: Literal["updated", "withdrawn"]
    updated_finding: FindingContract | None = None
    reason: str | None = None
    meta: MetaContract


