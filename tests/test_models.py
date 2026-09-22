import pytest
from pydantic import ValidationError

from backend.src.models import (
    AdvisoryResponse,
    AdvisoryStatus,
    ConditionTrace,
    ConditionTraceKind,
    ConditionTraceStatus,
    EvidencePlan,
    EvidenceRequirement,
    IntentUpdate,
    PolicyMatch,
    Severity,
    UserContext,
    WeatherFacts,
)
from backend.src.state import AdvisoryState


def test_partial_weather_preserves_missing_facts():
    weather = WeatherFacts(temperature_c=28.5)
    assert weather.temperature_c == 28.5
    assert weather.precipitation_mm is None
    assert weather.observed_at is None
    assert WeatherFacts().model_dump(exclude_none=True) == {}


@pytest.mark.parametrize("severity", ["LOW", "MODERATE", "HIGH", "SEVERE"])
def test_policy_severity_validates(severity):
    policy = PolicyMatch(
        policy_id="test-policy", title="Test policy", severity=severity,
        priority=1, guidance="Test guidance",
    )
    assert policy.severity is Severity(severity)
    assert policy.model_dump(mode="json")["severity"] == severity


def test_unknown_severity_is_rejected():
    with pytest.raises(ValidationError):
        PolicyMatch(
            policy_id="test-policy", title="Test policy", severity="UNKNOWN",
            priority=1, guidance="Test guidance",
        )


@pytest.mark.parametrize("values", [
    {"precipitation_probability": 101}, {"wind_speed_kmh": -1},
    {"latitude": 91}, {"longitude": -181},
])
def test_weather_rejects_invalid_ranges(values):
    with pytest.raises(ValidationError):
        WeatherFacts(**values)


def test_evidence_plan_parses_requirements():
    plan = EvidencePlan(requirements=[{
        "field": "wind_gust_kmh",
        "required_by": ["SOP-WIND-CYCLING-01"],
        "reason": "Needed to assess cycling conditions",
    }])
    assert isinstance(plan.requirements[0], EvidenceRequirement)
    assert plan.requirements[0].field == "wind_gust_kmh"
    with pytest.raises(ValidationError):
        EvidencePlan(requirements=[{"field": "wind_gust_kmh"}])


def test_advisory_response_round_trips():
    response = AdvisoryResponse(
        message="Example guidance for a test fixture.",
        resolved_context=UserContext(location="Bhopal", activity="cycling"),
        weather=WeatherFacts(wind_gust_kmh=12),
        matched_policies=[PolicyMatch(
            policy_id="test-policy", title="Test policy", severity=Severity.LOW,
            priority=1, guidance="Example guidance", trace=ConditionTrace(
                kind=ConditionTraceKind.LEAF,
                status=ConditionTraceStatus.EVALUATED,
                result=True,
                field="wind_gust_kmh",
                operator="gte",
                actual_value=12,
                expected_value=10,
            ),
        )],
        status=AdvisoryStatus.SUCCESS,
    )
    assert AdvisoryResponse.model_validate_json(response.model_dump_json()) == response


def test_clarification_response_without_weather():
    response = AdvisoryResponse(
        message="Which location?", resolved_context=UserContext(activity="cycling"),
        status=AdvisoryStatus.NEEDS_CLARIFICATION,
    )
    assert response.weather is None
    assert response.matched_policies == []


def test_state_defaults_are_independent():
    first = AdvisoryState(session_id="one", latest_user_message="Can I cycle?")
    second = AdvisoryState(session_id="two", latest_user_message="Can I walk?")
    first.user_context.activity = "cycling"
    first.evidence_plan.requirements.append(EvidenceRequirement(
        field="uv_index", required_by=["SOP-UV-PROLONGED-OUTDOOR-01"], reason="Sun exposure"
    ))
    assert second.user_context.activity is None
    assert second.evidence_plan.requirements == []
    assert second.weather is None


def test_intent_activity_fields_are_mutually_exclusive_and_normalized():
    update = IntentUpdate(unsupported_activity="  Stand-Up   Paddleboarding ")
    assert update.unsupported_activity == "stand-up paddleboarding"

    with pytest.raises(ValidationError, match="cannot both be populated"):
        IntentUpdate(activity="cycling", unsupported_activity="swimming")
