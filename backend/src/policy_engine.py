from enum import Enum

from pydantic import BaseModel, Field

from backend.src.models import (
    ConditionTrace,
    ConditionTraceKind,
    ConditionTraceStatus,
    PolicyMatch,
    Severity,
    WeatherFacts,
)
from backend.src.policies import Condition, ConditionOperator, SOP


class EvaluationStatus(str, Enum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    MISSING_EVIDENCE = "missing_evidence"


class PolicyEvaluation(BaseModel):
    policy_id: str
    matched: bool
    status: EvaluationStatus
    condition_trace: ConditionTrace


class PolicyEvaluationResult(BaseModel):
    evaluations: list[PolicyEvaluation] = Field(default_factory=list)
    matches: list[PolicyMatch] = Field(default_factory=list)


class PolicyEvaluationError(ValueError):
    pass


SEVERITY_RANK = {
    Severity.SEVERE: 4,
    Severity.HIGH: 3,
    Severity.MODERATE: 2,
    Severity.LOW: 1,
}


def evaluate_policies(
    policies: list[SOP],
    weather: WeatherFacts,
) -> PolicyEvaluationResult:
    evaluations = []
    matches = []

    for policy in sorted(policies, key=lambda item: item.id):
        status, trace = _evaluate_condition(policy.conditions, weather)
        matched = status is EvaluationStatus.MATCHED
        evaluations.append(
            PolicyEvaluation(
                policy_id=policy.id,
                matched=matched,
                status=status,
                condition_trace=trace,
            )
        )
        if matched:
            matches.append(
                PolicyMatch(
                    policy_id=policy.id,
                    title=policy.title,
                    severity=policy.severity,
                    priority=policy.priority,
                    guidance=policy.guidance,
                    trace=trace,
                )
            )

    matches.sort(
        key=lambda match: (
            -SEVERITY_RANK[match.severity],
            -match.priority,
            match.policy_id,
        )
    )
    return PolicyEvaluationResult(evaluations=evaluations, matches=matches)


def format_condition_trace(trace: ConditionTrace) -> str:
    if trace.kind is not ConditionTraceKind.LEAF:
        raise PolicyEvaluationError("Only leaf condition traces can be formatted")
    if trace.status is ConditionTraceStatus.MISSING_EVIDENCE:
        return f"{trace.field}: missing evidence"

    symbols = {
        ConditionOperator.GT.value: ">",
        ConditionOperator.GTE.value: ">=",
        ConditionOperator.LT.value: "<",
        ConditionOperator.LTE.value: "<=",
        ConditionOperator.EQ.value: "==",
        ConditionOperator.IN.value: "in",
        ConditionOperator.BETWEEN.value: "between",
    }
    outcome = "matched" if trace.result else "not matched"
    symbol = symbols.get(trace.operator or "", trace.operator or "")
    return (
        f"{trace.field}: {trace.actual_value} {symbol} "
        f"{trace.expected_value} -> {outcome}"
    )


def _evaluate_condition(
    condition: Condition,
    weather: WeatherFacts,
) -> tuple[EvaluationStatus, ConditionTrace]:
    if condition.field is not None:
        return _evaluate_leaf(condition, weather)

    if condition.all is not None:
        kind = ConditionTraceKind.ALL
        children = condition.all
    else:
        kind = ConditionTraceKind.ANY
        children = condition.any or []

    child_results = [_evaluate_condition(child, weather) for child in children]
    child_statuses = [status for status, _ in child_results]

    if kind is ConditionTraceKind.ALL:
        if EvaluationStatus.NOT_MATCHED in child_statuses:
            status = EvaluationStatus.NOT_MATCHED
        elif EvaluationStatus.MISSING_EVIDENCE in child_statuses:
            status = EvaluationStatus.MISSING_EVIDENCE
        else:
            status = EvaluationStatus.MATCHED
    else:
        if EvaluationStatus.MATCHED in child_statuses:
            status = EvaluationStatus.MATCHED
        elif EvaluationStatus.MISSING_EVIDENCE in child_statuses:
            status = EvaluationStatus.MISSING_EVIDENCE
        else:
            status = EvaluationStatus.NOT_MATCHED

    result = {
        EvaluationStatus.MATCHED: True,
        EvaluationStatus.NOT_MATCHED: False,
        EvaluationStatus.MISSING_EVIDENCE: None,
    }[status]
    trace_status = (
        ConditionTraceStatus.MISSING_EVIDENCE
        if status is EvaluationStatus.MISSING_EVIDENCE
        else ConditionTraceStatus.EVALUATED
    )
    return status, ConditionTrace(
        kind=kind,
        status=trace_status,
        result=result,
        children=[trace for _, trace in child_results],
    )


def _evaluate_leaf(
    condition: Condition,
    weather: WeatherFacts,
) -> tuple[EvaluationStatus, ConditionTrace]:
    field = condition.field
    operator = condition.operator
    if field is None or operator is None:
        raise PolicyEvaluationError("Leaf condition is incomplete")
    if field not in WeatherFacts.model_fields:
        raise PolicyEvaluationError(f"Unsupported weather field '{field}'")

    actual = getattr(weather, field)
    if actual is None:
        trace = ConditionTrace(
            kind=ConditionTraceKind.LEAF,
            status=ConditionTraceStatus.MISSING_EVIDENCE,
            result=None,
            field=field,
            operator=operator.value,
            actual_value=None,
            expected_value=condition.value,
        )
        return EvaluationStatus.MISSING_EVIDENCE, trace

    result = _apply_operator(actual, operator, condition.value)
    trace = ConditionTrace(
        kind=ConditionTraceKind.LEAF,
        status=ConditionTraceStatus.EVALUATED,
        result=result,
        field=field,
        operator=operator.value,
        actual_value=actual,
        expected_value=condition.value,
        margin=_numeric_margin(actual, operator, condition.value),
    )
    status = EvaluationStatus.MATCHED if result else EvaluationStatus.NOT_MATCHED
    return status, trace


def _apply_operator(actual: object, operator: ConditionOperator, expected: object) -> bool:
    if operator in {
        ConditionOperator.GT,
        ConditionOperator.GTE,
        ConditionOperator.LT,
        ConditionOperator.LTE,
    }:
        actual_number = _require_number(actual, "actual value")
        expected_number = _require_number(expected, "policy value")
        if operator is ConditionOperator.GT:
            return actual_number > expected_number
        if operator is ConditionOperator.GTE:
            return actual_number >= expected_number
        if operator is ConditionOperator.LT:
            return actual_number < expected_number
        return actual_number <= expected_number

    if operator is ConditionOperator.EQ:
        if isinstance(expected, list):
            raise PolicyEvaluationError("Operator 'eq' requires a scalar policy value")
        return actual == expected

    if operator is ConditionOperator.IN:
        if not isinstance(expected, list) or not expected:
            raise PolicyEvaluationError("Operator 'in' requires a non-empty policy list")
        return actual in expected

    if operator is ConditionOperator.BETWEEN:
        if not isinstance(expected, list) or len(expected) != 2:
            raise PolicyEvaluationError("Operator 'between' requires two policy values")
        actual_number = _require_number(actual, "actual value")
        lower = _require_number(expected[0], "lower policy value")
        upper = _require_number(expected[1], "upper policy value")
        return lower <= actual_number <= upper

    raise PolicyEvaluationError(f"Unsupported operator '{operator}'")


def _numeric_margin(
    actual: object,
    operator: ConditionOperator,
    expected: object,
) -> float | None:
    if not _is_number(actual) or not _is_number(expected):
        return None
    if operator in {ConditionOperator.GT, ConditionOperator.GTE}:
        return float(actual - expected)
    if operator in {ConditionOperator.LT, ConditionOperator.LTE}:
        return float(expected - actual)
    if operator is ConditionOperator.EQ:
        return float(abs(actual - expected))
    return None


def _require_number(value: object, name: str) -> int | float:
    if not _is_number(value):
        raise PolicyEvaluationError(f"{name.capitalize()} must be numeric")
    return value


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
