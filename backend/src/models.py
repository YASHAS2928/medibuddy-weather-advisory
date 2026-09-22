from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Severity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class UserContext(BaseModel):
    location: str | None = None
    activity: str | None = None
    unsupported_activity: str | None = Field(default=None, max_length=80)
    audience: str | None = None
    timeframe: str | None = None

    @model_validator(mode="after")
    def validate_activity_choice(self) -> "UserContext":
        if self.activity is not None and self.unsupported_activity is not None:
            raise ValueError(
                "activity and unsupported_activity cannot both be populated"
            )
        return self


class TimeReferenceKind(str, Enum):
    NOW = "now"
    TODAY = "today"
    MORNING = "morning"
    MIDDAY = "midday"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    TONIGHT = "tonight"
    TOMORROW = "tomorrow"
    TOMORROW_MORNING = "tomorrow_morning"
    TOMORROW_MIDDAY = "tomorrow_midday"
    TOMORROW_AFTERNOON = "tomorrow_afternoon"
    TOMORROW_EVENING = "tomorrow_evening"
    TOMORROW_NIGHT = "tomorrow_night"


class TimeReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TimeReferenceKind
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)

    @model_validator(mode="after")
    def validate_exact_time(self) -> "TimeReference":
        if self.hour is None and self.minute is not None:
            raise ValueError("minute requires an explicit hour")
        if self.hour is not None and self.kind not in {
            TimeReferenceKind.TODAY,
            TimeReferenceKind.TOMORROW,
        }:
            raise ValueError("explicit hours require today or tomorrow")
        return self

    def context_value(self) -> str:
        if self.hour is None:
            return self.kind.value
        minute = self.minute or 0
        return f"{self.kind.value}_at_{self.hour:02d}:{minute:02d}"


class IntentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str | None = Field(
        default=None,
        description=(
            "An explicit named geographic entity from the current user message that is "
            "suitable for geocoding, such as a city, town, region, state, or country. "
            "Generic venue or place-category expressions are not geographic updates."
        ),
    )
    activity: str | None = Field(
        default=None,
        description=(
            "The canonical supported activity when the current message clearly maps "
            "to one of the supplied allowed activities."
        ),
    )
    unsupported_activity: str | None = Field(
        default=None,
        max_length=80,
        description=(
            "A short normalized label for an explicit activity in the current message "
            "that does not map to any supplied canonical activity. Leave null when no "
            "activity is expressed. Labels mentioned only in instructions about how "
            "to fill the schema are not user activities and must remain null."
        ),
    )
    audience: str | None = None
    time_reference: TimeReference | None = Field(
        default=None,
        description=(
            "A controlled semantic time reference. Meal and part-of-day cues map to "
            "enum values: breakfast to morning; lunch, midday, and noon to midday; "
            "and dinner to evening. When an explicit clock time is present, use "
            "today or tomorrow with hour/minute instead of a broad part-of-day value."
        ),
    )

    @field_validator(
        "location",
        "activity",
        "unsupported_activity",
        "audience",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("unsupported_activity")
    @classmethod
    def normalize_unsupported_activity(cls, value: str | None) -> str | None:
        return " ".join(value.lower().split()) if value is not None else None

    @model_validator(mode="after")
    def validate_activity_choice(self) -> "IntentUpdate":
        if self.activity is not None and self.unsupported_activity is not None:
            raise ValueError(
                "activity and unsupported_activity cannot both be populated"
            )
        return self


class ResolvedLocation(BaseModel):
    query: str = Field(min_length=1)
    name: str = Field(min_length=1)
    admin1: str | None = None
    country: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(min_length=1)


class WeatherFacts(BaseModel):
    temperature_c: float | None = None
    apparent_temperature_c: float | None = None
    precipitation_mm: float | None = Field(default=None, ge=0)
    precipitation_probability: float | None = Field(default=None, ge=0, le=100)
    wind_speed_kmh: float | None = Field(default=None, ge=0)
    wind_gust_kmh: float | None = Field(default=None, ge=0)
    uv_index: float | None = Field(default=None, ge=0)
    weather_code: int | None = Field(default=None, ge=0)
    visibility_m: float | None = Field(default=None, ge=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str | None = None
    observed_at: datetime | None = None


class EvidenceRequirement(BaseModel):
    field: str
    required_by: list[str] = Field(min_length=1)
    reason: str


class EvidencePlan(BaseModel):
    requirements: list[EvidenceRequirement] = Field(default_factory=list)
    candidate_policy_ids: list[str] = Field(default_factory=list)


class ConditionTraceKind(str, Enum):
    LEAF = "leaf"
    ALL = "all"
    ANY = "any"


class ConditionTraceStatus(str, Enum):
    EVALUATED = "evaluated"
    MISSING_EVIDENCE = "missing_evidence"


TraceScalar = str | int | float | bool
TraceValue = TraceScalar | list[TraceScalar]


class ConditionTrace(BaseModel):
    kind: ConditionTraceKind
    status: ConditionTraceStatus
    result: bool | None
    field: str | None = None
    operator: str | None = None
    actual_value: TraceScalar | datetime | None = None
    expected_value: TraceValue | None = None
    margin: float | None = None
    children: list["ConditionTrace"] = Field(default_factory=list)


class PolicyMatch(BaseModel):
    policy_id: str
    title: str
    severity: Severity
    priority: int
    guidance: str
    trace: ConditionTrace | None = None


class AdvisoryStatus(str, Enum):
    SUCCESS = "success"
    NO_APPLICABLE_POLICY = "no_applicable_policy"
    NO_POLICY_MATCH = "no_policy_match"
    MISSING_CONTEXT = "missing_context"
    LOCATION_ERROR = "location_error"
    TIME_ERROR = "time_error"
    WEATHER_ERROR = "weather_error"
    INTENT_ERROR = "intent_error"
    INTERNAL_ERROR = "internal_error"
    NEEDS_CLARIFICATION = "needs_clarification"
    ERROR = "error"


class AdvisoryResponse(BaseModel):
    message: str
    resolved_context: UserContext
    weather: WeatherFacts | None = None
    matched_policies: list[PolicyMatch] = Field(default_factory=list)
    status: AdvisoryStatus
