from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.src.policies import Condition, SOP, required_fields
from backend.src.policy_loader import PolicyLoadError, load_policies


@pytest.fixture(scope="module")
def policies() -> list[SOP]:
    return load_policies()


def valid_policy_data() -> dict:
    return {
        "id": "SOP-TEST-01",
        "title": "Test policy",
        "category": "outdoor_activity",
        "severity": "LOW",
        "priority": 1,
        "applies_to": {"activities": ["walking"], "audiences": ["general"]},
        "conditions": {"field": "temperature_c", "operator": "gt", "value": 30},
        "guidance": "Use suitable precautions.",
    }


def write_policy_file(path: Path, policies: list[dict]) -> None:
    import yaml

    path.write_text(yaml.safe_dump({"sops": policies}, sort_keys=False), encoding="utf-8")


def test_real_sops_load(policies):
    assert len(policies) >= 10
    assert len({policy.id for policy in policies}) == len(policies)


def test_real_sops_cover_categories_and_severities(policies):
    assert len({policy.category for policy in policies}) >= 3
    assert {severity.value for severity in {policy.severity for policy in policies}} == {
        "LOW", "MODERATE", "HIGH", "SEVERE"
    }


def test_duplicate_ids_are_rejected(tmp_path):
    policy = valid_policy_data()
    path = tmp_path / "duplicates.yaml"
    write_policy_file(path, [policy, policy])
    with pytest.raises(PolicyLoadError, match="Duplicate SOP IDs: SOP-TEST-01"):
        load_policies(path)


def test_invalid_severity_is_rejected():
    policy = valid_policy_data()
    policy["severity"] = "CRITICAL"
    with pytest.raises(ValidationError):
        SOP.model_validate(policy)


def test_missing_conditions_are_rejected():
    policy = valid_policy_data()
    del policy["conditions"]
    with pytest.raises(ValidationError):
        SOP.model_validate(policy)


@pytest.mark.parametrize("condition", [
    {},
    {"all": []},
    {"all": [{"field": "uv_index", "operator": "gte", "value": 8}], "any": []},
    {"field": "uv_index", "operator": "gte"},
    {"field": "uv_index", "operator": "gte", "value": 8, "all": []},
    {"field": "uv_index", "operator": "in", "value": []},
    {"field": "uv_index", "operator": "between", "value": [8]},
])
def test_malformed_condition_structures_are_rejected(condition):
    with pytest.raises(ValidationError):
        Condition.model_validate(condition)


def test_single_condition_required_fields(policies):
    policy = next(policy for policy in policies if policy.id == "SOP-WIND-CYCLING-01")
    assert required_fields(policy) == {"wind_speed_kmh"}


def test_nested_condition_required_fields(policies):
    policy = next(policy for policy in policies if policy.id == "SOP-RAIN-WIND-EVENT-01")
    assert required_fields(policy) == {
        "precipitation_mm", "wind_speed_kmh", "wind_gust_kmh"
    }


def test_real_sops_include_multiple_weather_conditions(policies):
    assert any(len(required_fields(policy)) > 1 for policy in policies)


def test_real_sops_include_fuzzy_intent_examples(policies):
    fuzzy_policies = [policy for policy in policies if policy.intent_examples]
    assert fuzzy_policies
    assert any(policy.applies_to.activities[0] == "picnic" for policy in fuzzy_policies)


def test_malformed_yaml_fails_clearly(tmp_path):
    path = tmp_path / "malformed.yaml"
    path.write_text("sops: [", encoding="utf-8")
    with pytest.raises(PolicyLoadError, match="Malformed policy YAML"):
        load_policies(path)
