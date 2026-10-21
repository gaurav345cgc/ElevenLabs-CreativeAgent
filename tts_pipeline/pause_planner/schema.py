"""Pause plan schema — structured holds from the OpenAI pause planner."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PauseHoldKind(StrEnum):
    """Why a silence hold was placed."""

    PRACTICE = "practice"
    SECTION = "section"
    INTEGRATION = "integration"
    OTHER = "other"


class PausePlannerProvider(StrEnum):
    """Which provider produced the pause plan."""

    OPENAI = "openai"
    HUMAN = "human"
    LOCAL = "local"


class PauseHold(BaseModel):
    """One silence hold anchored to a beat or paragraph index."""

    model_config = ConfigDict(frozen=True)

    hold_id: str = Field(min_length=1)
    after_beat_index: int | None = Field(default=None, ge=0)
    after_paragraph_index: int | None = Field(default=None, ge=0)
    hold_seconds: int = Field(ge=1)
    kind: PauseHoldKind
    reason: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def _exactly_one_anchor(self) -> PauseHold:
        has_beat = self.after_beat_index is not None
        has_paragraph = self.after_paragraph_index is not None
        if has_beat == has_paragraph:
            raise ValueError(
                "exactly one of after_beat_index or after_paragraph_index is required"
            )
        return self


def _sum_hold_seconds(holds: object) -> int:
    if not isinstance(holds, list):
        return 0
    total = 0
    for hold in holds:
        if isinstance(hold, dict):
            total += int(hold.get("hold_seconds") or 0)
        else:
            total += int(getattr(hold, "hold_seconds", 0) or 0)
    return total


class PausePlan(BaseModel):
    """Normalized pause plan from the planner (before chunk mapping)."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    planner: PausePlannerProvider
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    target_duration_seconds: int | None = Field(default=None, ge=0)
    estimated_speech_seconds: int | None = Field(default=None, ge=0)
    total_hold_seconds: int = Field(ge=0)
    holds: list[PauseHold] = Field(default_factory=list)
    raw_response_sha256: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _recompute_total_hold_seconds(cls, data: object) -> object:
        if isinstance(data, dict):
            data = dict(data)
            data["total_hold_seconds"] = _sum_hold_seconds(data.get("holds"))
        return data

    @model_validator(mode="after")
    def _unique_hold_ids(self) -> PausePlan:
        hold_ids = [hold.hold_id for hold in self.holds]
        if len(hold_ids) != len(set(hold_ids)):
            raise ValueError("hold_id values must be unique within a pause plan")
        return self


class MappedPauseHold(BaseModel):
    """Pause hold after mapping onto a TTS speech chunk index."""

    model_config = ConfigDict(frozen=True)

    hold_id: str = Field(min_length=1)
    after_beat_index: int | None = Field(default=None, ge=0)
    after_paragraph_index: int | None = Field(default=None, ge=0)
    after_chunk_index: int = Field(ge=0)
    hold_seconds: int = Field(ge=1)
    kind: PauseHoldKind
    reason: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def _exactly_one_source_anchor(self) -> MappedPauseHold:
        has_beat = self.after_beat_index is not None
        has_paragraph = self.after_paragraph_index is not None
        if has_beat == has_paragraph:
            raise ValueError(
                "exactly one of after_beat_index or after_paragraph_index is required"
            )
        return self


class MappedPausePlan(BaseModel):
    """Pause plan mapped onto speech chunk indices for stitch intercalation."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    total_hold_seconds: int = Field(ge=0)
    holds: list[MappedPauseHold] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _recompute_total_hold_seconds(cls, data: object) -> object:
        if isinstance(data, dict):
            data = dict(data)
            data["total_hold_seconds"] = _sum_hold_seconds(data.get("holds"))
        return data

    @model_validator(mode="after")
    def _unique_hold_ids(self) -> MappedPausePlan:
        hold_ids = [hold.hold_id for hold in self.holds]
        if len(hold_ids) != len(set(hold_ids)):
            raise ValueError("hold_id values must be unique within a mapped pause plan")
        return self
