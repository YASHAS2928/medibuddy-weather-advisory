import pytest

from backend.src.evidence_planner import EvidencePlanningError, build_evidence_plan
from backend.src.models import UserContext
from backend.src.policies import SOP, required_fields
from backend.src.policy_loader import load_policies


@pytest.fixture(scope="module")
def policies() -> list[SOP]:
    return load_policies()


def make_policy(
    policy_id: str,
    field: str,
    activity: str = "cycling",
    audiences: list[str] | None = None,
) -> SOP:
    return SOP.model_validate({
        "id": policy_id,
        "title": "Test policy",
        "category": "outdoor_activity",
        "severity": "MODERATE",
        "priority": 50,
        "applies_to": {
            "activities": [activity],
            "audiences": audiences or ["general"],
        },
        "conditions": {"field": field, "operator": "gte", "value": 1},
        "guidance": "Use appropriate precautions.",
    })


def fields_in(plan) -> list[str]:
    return [requirement.field for requirement in plan.requirements]


def test_cycling_context_uses_only_applicable_policies(policies):
    plan = build_evidence_plan(
        UserContext(location="Bhopal", activity="cycling", audience="adult", timeframe="today"),
        policies,
    )
    candidates = [
        policy for policy in policies
        if "cycling" in set(policy.applies_to.activities)
        and (
            "general" in set(policy.applies_to.audiences)
            or "adult" in set(policy.applies_to.audiences)
        )
    ]
    expected_fields = sorted(set().union(*(required_fields(policy) for policy in candidates)))

    assert plan.candidate_policy_ids == sorted(policy.id for policy in candidates)
    assert fields_in(plan) == expected_fields
    assert plan.candidate_policy_ids == ["SOP-WIND-CYCLING-01"]


def test_travel_context_produces_a_different_plan(policies):
    cycling_plan = build_evidence_plan(UserContext(activity="cycling", audience="adult"), policies)
    travel_plan = build_evidence_plan(UserContext(activity="travel", audience="adult"), policies)

    assert travel_plan.candidate_policy_ids == [
        "SOP-RAIN-TRAVEL-01",
        "SOP-VISIBILITY-TRAVEL-01",
    ]
    assert fields_in(travel_plan) == ["precipitation_mm", "visibility_m"]
    assert fields_in(travel_plan) != fields_in(cycling_plan)


def test_elderly_context_includes_specific_and_general_policies(policies):
    plan = build_evidence_plan(UserContext(activity="travel", audience="elderly"), policies)

    assert plan.candidate_policy_ids == [
        "SOP-HEAT-ELDERLY-01",
        "SOP-RAIN-TRAVEL-01",
        "SOP-VISIBILITY-TRAVEL-01",
    ]
    assert fields_in(plan) == ["apparent_temperature_c", "precipitation_mm", "visibility_m"]


def test_general_audience_policy_applies_to_specific_audience(policies):
    general_policy = make_policy(
        "SOP-GENERAL-CYCLING-01",
        "temperature_c",
        audiences=["general"],
    )
    plan = build_evidence_plan(
        UserContext(activity="cycling", audience="elderly"),
        [general_policy],
    )

    assert plan.candidate_policy_ids == ["SOP-GENERAL-CYCLING-01"]
    assert fields_in(plan) == ["temperature_c"]


def test_known_adult_excludes_other_specific_audiences(policies):
    plan = build_evidence_plan(UserContext(activity="travel", audience="adult"), policies)

    assert "SOP-HEAT-ELDERLY-01" not in plan.candidate_policy_ids
    assert "SOP-HEAT-CHILDREN-01" not in plan.candidate_policy_ids


def test_missing_activity_plans_conservatively(policies):
    plan = build_evidence_plan(UserContext(activity=None, audience="adult"), policies)

    assert plan.candidate_policy_ids
    assert "SOP-WIND-CYCLING-01" in plan.candidate_policy_ids
    assert "SOP-RAIN-TRAVEL-01" in plan.candidate_policy_ids
    assert "SOP-HEAT-ELDERLY-01" not in plan.candidate_policy_ids


def test_explicit_uncovered_activity_produces_no_plan(policies):
    plan = build_evidence_plan(
        UserContext(
            location="Bhopal",
            activity=None,
            unsupported_activity="swimming",
            audience="adult",
        ),
        policies,
    )

    assert plan.candidate_policy_ids == []
    assert plan.requirements == []


def test_missing_audience_plans_conservatively(policies):
    plan = build_evidence_plan(UserContext(activity="travel", audience=None), policies)

    assert "SOP-HEAT-ELDERLY-01" in plan.candidate_policy_ids
    assert "SOP-HEAT-CHILDREN-01" in plan.candidate_policy_ids
    assert "SOP-RAIN-TRAVEL-01" in plan.candidate_policy_ids


def test_duplicate_fields_have_one_requirement_with_all_sources(policies):
    extra_policy = make_policy("SOP-WIND-CYCLING-02", "wind_speed_kmh")
    plan = build_evidence_plan(
        UserContext(activity="cycling", audience="adult"),
        [*policies, extra_policy],
    )
    wind_requirements = [
        requirement for requirement in plan.requirements
        if requirement.field == "wind_speed_kmh"
    ]

    assert len(wind_requirements) == 1
    assert wind_requirements[0].required_by == [
        "SOP-WIND-CYCLING-01",
        "SOP-WIND-CYCLING-02",
    ]
    assert wind_requirements[0].reason == "Required to evaluate 2 candidate policies."


def test_nested_condition_fields_are_included(policies):
    plan = build_evidence_plan(UserContext(activity="outdoor_event", audience="adult"), policies)

    assert {
        "precipitation_mm", "wind_speed_kmh", "wind_gust_kmh"
    }.issubset(fields_in(plan))
    assert "SOP-RAIN-WIND-EVENT-01" in plan.candidate_policy_ids


def test_unsupported_weather_field_fails_clearly(policies):
    unsupported = make_policy("SOP-WIND-TYPO-01", "wind_sped_kmh")

    with pytest.raises(
        EvidencePlanningError,
        match="Unsupported weather field 'wind_sped_kmh' referenced by policy SOP-WIND-TYPO-01",
    ):
        build_evidence_plan(UserContext(activity="cycling", audience="adult"), [*policies, unsupported])


def test_new_sop_automatically_participates_in_planning(policies):
    additional = make_policy("SOP-TEMP-CYCLING-01", "temperature_c")
    plan = build_evidence_plan(
        UserContext(activity="cycling", audience="adult"),
        [*policies, additional],
    )
    temperature = next(
        requirement for requirement in plan.requirements
        if requirement.field == "temperature_c"
    )

    assert "SOP-TEMP-CYCLING-01" in plan.candidate_policy_ids
    assert temperature.required_by == ["SOP-TEMP-CYCLING-01"]


def test_plan_order_is_deterministic(policies):
    context = UserContext(activity=None, audience=None)
    first = build_evidence_plan(context, policies)
    second = build_evidence_plan(context, list(reversed(policies)))

    assert first == second
    assert first.candidate_policy_ids == sorted(first.candidate_policy_ids)
    assert fields_in(first) == sorted(fields_in(first))
    assert all(
        requirement.required_by == sorted(requirement.required_by)
        for requirement in first.requirements
    )
