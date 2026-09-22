from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.src.models import (
    AdvisoryStatus,
    PolicyMatch,
    ResolvedLocation,
    UserContext,
    WeatherFacts,
)
from backend.src.policy_engine import PolicyEvaluation


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)

    @field_validator("message", "session_id", mode="before")
    @classmethod
    def reject_blank_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value


class ChatResponse(BaseModel):
    status: AdvisoryStatus
    message: str
    resolved_context: UserContext
    resolved_location: ResolvedLocation | None = None
    target_time: datetime | None = None
    weather: WeatherFacts | None = None
    candidate_policy_ids: list[str] = Field(default_factory=list)
    policy_evaluations: list[PolicyEvaluation] = Field(default_factory=list)
    matched_policies: list[PolicyMatch] = Field(default_factory=list)
