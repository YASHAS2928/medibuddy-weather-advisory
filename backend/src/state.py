from datetime import datetime

from pydantic import BaseModel, Field

from backend.src.models import (
    AdvisoryStatus,
    AdvisoryResponse,
    EvidencePlan,
    IntentUpdate,
    PolicyMatch,
    ResolvedLocation,
    TimeReference,
    UserContext,
    WeatherFacts,
)
from backend.src.policy_engine import PolicyEvaluation


class AdvisoryState(BaseModel):
    latest_user_message: str
    session_id: str
    user_context: UserContext = Field(default_factory=UserContext)
    intent_update: IntentUpdate | None = None
    time_reference: TimeReference | None = None
    resolved_location: ResolvedLocation | None = None
    target_time: datetime | None = None
    evidence_plan: EvidencePlan = Field(default_factory=EvidencePlan)
    weather: WeatherFacts | None = None
    policy_evaluations: list[PolicyEvaluation] = Field(default_factory=list)
    matched_policies: list[PolicyMatch] = Field(default_factory=list)
    response: AdvisoryResponse | None = None
    error: str | None = None
    status: AdvisoryStatus | None = None
