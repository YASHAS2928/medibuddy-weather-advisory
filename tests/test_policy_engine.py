import pytest
from pydantic import ValidationError

from backend.src.evidence_planner import build_evidence_plan
from backend.src.models import ConditionTraceStatus, Severity, UserContext, WeatherFacts
from backend.src.policies import SOP
from backend.src.policy_engine import (
    EvaluationStatus,
    evaluate_policies,
    format_condition_trace,
)
from backend.src.policy_loader import load_policies


def make_policy(
    policy_id: str = "SOP-TEST-01",
    condition: dict | None = None,
    severity: str = "MODERATE",
    priority: int = 50,
) -> SOP:
    return SOP.model_validate({
        "id": policy_id,
        "title": "Test policy",
        "category": "outdoor_activity",
        "severity": severity,
        "priority": priority,
        "applies_to": {"activities": ["cycling"], "audiences": ["general"]},
        "conditions": condition or {
            "field": "wind_speed_kmh", "operator": "gt", "value": 40,
        },
        "guidance": "Use appropriate precautions.",
    })


def evaluate_one(condition: dict, weather: WeatherFacts):
    result = evaluate_policies([make_policy(condition=condition)], weather)
    return result.evaluations[0]


def candidates_for(context: UserContext, policies: list[SOP]) -> list[SOP]:
    plan = build_evidence_plan(context, policies)
    candidate_ids = set(plan.candidate_policy_ids)
    return [policy for policy in policies if policy.id in candidate_ids]


def test_gt_match_and_trace_statement():
    evaluation = evaluate_one(
        {"field": "wind_speed_kmh", "operator": "gt", "value": 40},
        WeatherFacts(wind_speed_kmh=46),
    )

    assert evaluation.status is EvaluationStatus.MATCHED
    assert evaluation.matched is True
    assert format_condition_trace(evaluation.condition_trace) == (
        "wind_speed_kmh: 46.0 > 40 -> matched"
    )


def test_gt_non_match():
    evaluation = evaluate_one(
        {"field": "wind_speed_kmh", "operator": "gt", "value": 40},
        WeatherFacts(wind_speed_kmh=35),
    )
    assert evaluation.status is EvaluationStatus.NOT_MATCHED
    assert evaluation.matched is False


def test_gte_exact_boundary_matches():
    evaluation = evaluate_one(
        {"field": "wind_speed_kmh", "operator": "gte", "value": 40},
        WeatherFacts(wind_speed_kmh=40),
    )
    assert evaluation.status is EvaluationStatus.MATCHED


@pytest.mark.parametrize(("operator", "actual", "expected", "matched"), [
    ("lt", 999, 1000, True),
    ("lte", 1000, 1000, True),
    ("lt", 1000, 1000, False),
])
def test_lt_and_lte(operator, actual, expected, matched):
    evaluation = evaluate_one(
        {"field": "visibility_m", "operator": operator, "value": expected},
        WeatherFacts(visibility_m=actual),
    )
    assert evaluation.matched is matched


def test_eq_matches():
    evaluation = evaluate_one(
        {"field": "weather_code", "operator": "eq", "value": 95},
        WeatherFacts(weather_code=95),
    )
    assert evaluation.status is EvaluationStatus.MATCHED


def test_in_matches_current_list_shape():
    evaluation = evaluate_one(
        {"field": "weather_code", "operator": "in", "value": [95, 96, 99]},
        WeatherFacts(weather_code=96),
    )
    assert evaluation.status is EvaluationStatus.MATCHED


@pytest.mark.parametrize(("actual", "matched"), [
    (30, True),
    (45, True),
    (59, True),
    (60, False),
])
def test_between_is_inclusive(actual, matched):
    evaluation = evaluate_one(
        {"field": "precipitation_probability", "operator": "between", "value": [30, 59]},
        WeatherFacts(precipitation_probability=actual),
    )
    assert evaluation.matched is matched


def test_nested_all_requires_every_child():
    condition = {"all": [
        {"field": "precipitation_mm", "operator": "gte", "value": 5},
        {"field": "wind_speed_kmh", "operator": "gte", "value": 30},
    ]}
    matched = evaluate_one(
        condition,
        WeatherFacts(precipitation_mm=5, wind_speed_kmh=30),
    )
    not_matched = evaluate_one(
        condition,
        WeatherFacts(precipitation_mm=4, wind_speed_kmh=30),
    )

    assert matched.status is EvaluationStatus.MATCHED
    assert not_matched.status is EvaluationStatus.NOT_MATCHED


def test_nested_any_matches_when_one_child_matches():
    condition = {"any": [
        {"field": "wind_speed_kmh", "operator": "gte", "value": 30},
        {"field": "wind_gust_kmh", "operator": "gte", "value": 45},
    ]}
    evaluation = evaluate_one(
        condition,
        WeatherFacts(wind_speed_kmh=20, wind_gust_kmh=45),
    )
    assert evaluation.status is EvaluationStatus.MATCHED


def test_missing_evidence_is_explicit_and_does_not_match():
    result = evaluate_policies([make_policy()], WeatherFacts())
    evaluation = result.evaluations[0]

    assert result.matches == []
    assert evaluation.status is EvaluationStatus.MISSING_EVIDENCE
    assert evaluation.condition_trace.status is ConditionTraceStatus.MISSING_EVIDENCE
    assert evaluation.condition_trace.actual_value is None
    assert evaluation.condition_trace.result is None
    assert format_condition_trace(evaluation.condition_trace) == "wind_speed_kmh: missing evidence"


def test_all_with_missing_evidence_does_not_match():
    condition = {"all": [
        {"field": "precipitation_mm", "operator": "gte", "value": 5},
        {"field": "wind_speed_kmh", "operator": "gte", "value": 30},
    ]}
    evaluation = evaluate_one(condition, WeatherFacts(precipitation_mm=5))
    assert evaluation.status is EvaluationStatus.MISSING_EVIDENCE
    assert evaluation.matched is False


def test_any_can_match_with_another_branch_missing():
    condition = {"any": [
        {"field": "wind_speed_kmh", "operator": "gte", "value": 30},
        {"field": "wind_gust_kmh", "operator": "gte", "value": 45},
    ]}
    evaluation = evaluate_one(condition, WeatherFacts(wind_speed_kmh=30))
    assert evaluation.status is EvaluationStatus.MATCHED
    assert evaluation.condition_trace.children[1].status is ConditionTraceStatus.MISSING_EVIDENCE


def test_any_without_true_branch_preserves_missing_evidence():
    condition = {"any": [
        {"field": "wind_speed_kmh", "operator": "gte", "value": 30},
        {"field": "wind_gust_kmh", "operator": "gte", "value": 45},
    ]}
    evaluation = evaluate_one(condition, WeatherFacts(wind_speed_kmh=20))
    assert evaluation.status is EvaluationStatus.MISSING_EVIDENCE


def test_matches_sort_by_severity_priority_then_id():
    policies = [
        make_policy("SOP-LOW-01", severity="LOW", priority=100),
        make_policy("SOP-MODERATE-01", severity="MODERATE", priority=100),
        make_policy("SOP-HIGH-LOW-PRIORITY-01", severity="HIGH", priority=10),
        make_policy("SOP-HIGH-B-01", severity="HIGH", priority=80),
        make_policy("SOP-HIGH-A-01", severity="HIGH", priority=80),
        make_policy("SOP-SEVERE-01", severity="SEVERE", priority=1),
    ]
    result = evaluate_policies(policies, WeatherFacts(wind_speed_kmh=46))

    assert [match.policy_id for match in result.matches] == [
        "SOP-SEVERE-01",
        "SOP-HIGH-A-01",
        "SOP-HIGH-B-01",
        "SOP-HIGH-LOW-PRIORITY-01",
        "SOP-MODERATE-01",
        "SOP-LOW-01",
    ]
    assert len(result.matches) == len(policies)


def test_numeric_margin_is_calculated_in_python():
    evaluation = evaluate_one(
        {"field": "wind_speed_kmh", "operator": "gt", "value": 40},
        WeatherFacts(wind_speed_kmh=46.2),
    )
    assert evaluation.condition_trace.margin == pytest.approx(6.2)


def test_dynamic_sop_evaluates_without_engine_changes():
    policy = make_policy(
        "SOP-TEMP-DYNAMIC-01",
        {"field": "temperature_c", "operator": "lte", "value": 25},
    )
    result = evaluate_policies([policy], WeatherFacts(temperature_c=24))

    assert [match.policy_id for match in result.matches] == ["SOP-TEMP-DYNAMIC-01"]
    assert result.matches[0].trace.actual_value == 24


def test_unknown_operator_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        make_policy(condition={
            "field": "wind_speed_kmh", "operator": "approximately", "value": 40,
        })


def test_real_cycling_policy_matches():
    policies = load_policies()
    candidates = candidates_for(UserContext(activity="cycling", audience="adult"), policies)
    result = evaluate_policies(candidates, WeatherFacts(wind_speed_kmh=46.2))

    assert [match.policy_id for match in result.matches] == ["SOP-WIND-CYCLING-01"]
    assert result.matches[0].trace.margin == pytest.approx(6.2)


def test_real_travel_policies_match_and_are_ordered():
    policies = load_policies()
    candidates = candidates_for(UserContext(activity="travel", audience="adult"), policies)
    result = evaluate_policies(
        candidates,
        WeatherFacts(precipitation_mm=10, visibility_m=900),
    )

    assert [match.policy_id for match in result.matches] == [
        "SOP-VISIBILITY-TRAVEL-01",
        "SOP-RAIN-TRAVEL-01",
    ]


def test_real_vulnerable_person_policy_matches():
    policies = load_policies()
    candidates = candidates_for(UserContext(activity="travel", audience="elderly"), policies)
    result = evaluate_policies(
        candidates,
        WeatherFacts(apparent_temperature_c=35, precipitation_mm=0, visibility_m=5000),
    )
    assert [match.policy_id for match in result.matches] == ["SOP-HEAT-ELDERLY-01"]
    assert result.matches[0].severity is Severity.HIGH


def test_real_multi_condition_policy_matches_with_true_any_branch():
    policies = load_policies()
    candidates = candidates_for(UserContext(activity="outdoor_event", audience="adult"), policies)
    result = evaluate_policies(
        candidates,
        WeatherFacts(
            precipitation_mm=5,
            wind_speed_kmh=30,
            wind_gust_kmh=None,
            weather_code=1,
            uv_index=1,
        ),
    )
    assert "SOP-RAIN-WIND-EVENT-01" in {
        match.policy_id for match in result.matches
    }
