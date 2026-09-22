from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, StringConstraints, model_validator

from backend.src.models import Severity


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ConditionScalar = StrictStr | StrictInt | StrictFloat | StrictBool
ConditionValue = ConditionScalar | list[ConditionScalar]


class ConditionOperator(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    IN = "in"
    BETWEEN = "between"


class PolicyCategory(str, Enum):
    OUTDOOR_ACTIVITY = "outdoor_activity"
    TRAVEL = "travel"
    VULNERABLE_PEOPLE = "vulnerable_people"


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: NonEmptyString | None = None
    operator: ConditionOperator | None = None
    value: ConditionValue | None = None
    all: list["Condition"] | None = None
    any: list["Condition"] | None = None

    @model_validator(mode="after")
    def validate_structure(self) -> "Condition":
        leaf_parts = (self.field, self.operator, self.value)
        has_leaf = any(part is not None for part in leaf_parts)
        groups = [group for group in (self.all, self.any) if group is not None]

        if has_leaf:
            if not all(part is not None for part in leaf_parts):
                raise ValueError("leaf conditions require field, operator, and value")
            if groups:
                raise ValueError("a condition cannot be both a leaf and a group")
            self._validate_operator_value()
            return self

        if len(groups) != 1:
            raise ValueError("a condition group requires exactly one of all or any")
        if not groups[0]:
            raise ValueError("condition groups cannot be empty")
        return self

    def _validate_operator_value(self) -> None:
        if self.operator in {
            ConditionOperator.GT,
            ConditionOperator.GTE,
            ConditionOperator.LT,
            ConditionOperator.LTE,
        } and not _is_number(self.value):
            raise ValueError(f"operator '{self.operator.value}' requires a numeric value")

        if self.operator is ConditionOperator.IN:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("operator 'in' requires a non-empty list")

        if self.operator is ConditionOperator.EQ and isinstance(self.value, list):
            raise ValueError("operator 'eq' requires a scalar value")

        if self.operator is ConditionOperator.BETWEEN:
            if (
                not isinstance(self.value, list)
                or len(self.value) != 2
                or not all(_is_number(item) for item in self.value)
            ):
                raise ValueError("operator 'between' requires two numeric values")
            if self.value[0] > self.value[1]:
                raise ValueError("operator 'between' requires values in ascending order")


class PolicyApplicability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activities: list[NonEmptyString] = Field(min_length=1)
    audiences: list[NonEmptyString] = Field(min_length=1)


class SOP(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyString = Field(pattern=r"^SOP-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
    title: NonEmptyString
    category: PolicyCategory
    severity: Severity
    priority: int = Field(ge=1, le=100)
    applies_to: PolicyApplicability
    conditions: Condition
    guidance: NonEmptyString
    rationale: NonEmptyString | None = None
    intent_examples: list[NonEmptyString] = Field(default_factory=list, max_length=3)


def required_fields(policy: SOP) -> set[str]:
    return _condition_fields(policy.conditions)


def _condition_fields(condition: Condition) -> set[str]:
    if condition.field is not None:
        return {condition.field}

    children = condition.all if condition.all is not None else condition.any
    fields: set[str] = set()
    for child in children or []:
        fields.update(_condition_fields(child))
    return fields


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
