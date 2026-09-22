"""LangGraph orchestration for the weather-advisory assistant."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
import logging
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from backend.src.context import merge_context
from backend.src.evidence_planner import EvidencePlanningError, build_evidence_plan
from backend.src.geocoding import LocationResolutionError, resolve_location
from backend.src.intent import IntentExtractionError, extract_intent
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
    ResolvedLocation,
    Severity,
    TimeReference,
    TimeReferenceKind,
    UserContext,
    WeatherFacts,
)
from backend.src.policy_engine import (
    EvaluationStatus,
    PolicyEvaluation,
    PolicyEvaluationError,
    evaluate_policies,
)
from backend.src.policy_loader import load_policies
from backend.src.policies import SOP
from backend.src.state import AdvisoryState
from backend.src.time_resolver import TimeResolutionError, resolve_target_time
from backend.src.weather import WeatherDataError, WeatherServiceError, fetch_weather


IntentExtractor = Callable[
    [str, list[SOP], UserContext | None], Awaitable[IntentUpdate]
]
LocationResolver = Callable[[str], Awaitable[ResolvedLocation]]
WeatherFetcher = Callable[
    [ResolvedLocation, EvidencePlan, datetime], Awaitable[WeatherFacts]
]

logger = logging.getLogger(__name__)


def _response_update(
    state: AdvisoryState,
    status: AdvisoryStatus,
    message: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "response": AdvisoryResponse(
            message=message,
            resolved_context=state.user_context,
            weather=state.weather,
            matched_policies=state.matched_policies,
            status=status,
        ),
    }


def create_graph(
    *,
    policies: list[SOP] | None = None,
    intent_extractor: IntentExtractor = extract_intent,
    location_resolver: LocationResolver = resolve_location,
    weather_fetcher: WeatherFetcher = fetch_weather,
    clock: Callable[[], datetime] | None = None,
    checkpointer: InMemorySaver | None = None,
):
    """Build and compile the advisory graph with injectable I/O boundaries."""

    active_policies = list(policies) if policies is not None else load_policies()
    policies_by_id = {policy.id: policy for policy in active_policies}

    async def extract_intent_node(state: AdvisoryState) -> dict[str, Any]:
        reset: dict[str, Any] = {
            "intent_update": None,
            "resolved_location": None,
            "target_time": None,
            "evidence_plan": EvidencePlan(),
            "weather": None,
            "policy_evaluations": [],
            "matched_policies": [],
            "response": None,
            "error": None,
            "status": None,
        }
        try:
            update = await intent_extractor(
                state.latest_user_message,
                active_policies,
                state.user_context,
            )
            return {**reset, "intent_update": update}
        except IntentExtractionError as exc:
            return {
                **reset,
                "error": str(exc),
                "status": AdvisoryStatus.INTENT_ERROR,
            }
        except Exception as exc:  # pragma: no cover - defensive boundary
            return {
                **reset,
                "error": str(exc),
                "status": AdvisoryStatus.INTERNAL_ERROR,
            }

    def merge_context_node(state: AdvisoryState) -> dict[str, Any]:
        update = state.intent_update or IntentUpdate()
        merged = merge_context(state.user_context, update)
        reference = (
            update.time_reference
            or state.time_reference
            or TimeReference(kind=TimeReferenceKind.NOW)
        )
        if merged.timeframe is None:
            merged = merged.model_copy(update={"timeframe": reference.context_value()})
        return {"user_context": merged, "time_reference": reference}

    def validate_context_node(state: AdvisoryState) -> dict[str, Any]:
        if not state.user_context.location:
            return {
                "error": "A location is required before weather can be resolved.",
                "status": AdvisoryStatus.MISSING_CONTEXT,
            }
        return {}

    async def resolve_location_node(state: AdvisoryState) -> dict[str, Any]:
        try:
            location = await location_resolver(state.user_context.location or "")
            return {"resolved_location": location}
        except LocationResolutionError as exc:
            return {"error": str(exc), "status": AdvisoryStatus.LOCATION_ERROR}
        except Exception as exc:  # pragma: no cover - defensive boundary
            return {"error": str(exc), "status": AdvisoryStatus.INTERNAL_ERROR}

    def resolve_time_node(state: AdvisoryState) -> dict[str, Any]:
        try:
            target = resolve_target_time(
                state.time_reference or TimeReference(kind=TimeReferenceKind.NOW),
                state.resolved_location.timezone,  # type: ignore[union-attr]
                now=clock() if clock is not None else None,
            )
            return {"target_time": target}
        except TimeResolutionError as exc:
            return {"error": str(exc), "status": AdvisoryStatus.TIME_ERROR}
        except Exception as exc:  # pragma: no cover - defensive boundary
            return {"error": str(exc), "status": AdvisoryStatus.INTERNAL_ERROR}

    def build_evidence_plan_node(state: AdvisoryState) -> dict[str, Any]:
        try:
            plan = build_evidence_plan(state.user_context, active_policies)
            missing = [
                policy_id
                for policy_id in plan.candidate_policy_ids
                if policy_id not in policies_by_id
            ]
            if missing:
                raise EvidencePlanningError(
                    f"Evidence plan references unknown policies: {', '.join(missing)}"
                )
            return {"evidence_plan": plan}
        except Exception as exc:
            return {"error": str(exc), "status": AdvisoryStatus.INTERNAL_ERROR}

    async def fetch_weather_node(state: AdvisoryState) -> dict[str, Any]:
        try:
            weather = await weather_fetcher(
                state.resolved_location,  # type: ignore[arg-type]
                state.evidence_plan,
                state.target_time,  # type: ignore[arg-type]
            )
            return {"weather": weather}
        except (WeatherServiceError, WeatherDataError) as exc:
            logger.warning(
                "Weather evidence fetch failed: type=%s reason=%s",
                type(exc).__name__,
                exc,
            )
            return {"error": str(exc), "status": AdvisoryStatus.WEATHER_ERROR}
        except Exception as exc:  # pragma: no cover - defensive boundary
            return {"error": str(exc), "status": AdvisoryStatus.INTERNAL_ERROR}

    def evaluate_policies_node(state: AdvisoryState) -> dict[str, Any]:
        try:
            candidates = [
                policies_by_id[policy_id]
                for policy_id in state.evidence_plan.candidate_policy_ids
            ]
            result = evaluate_policies(candidates, state.weather)  # type: ignore[arg-type]
            return {
                "policy_evaluations": result.evaluations,
                "matched_policies": result.matches,
            }
        except (KeyError, PolicyEvaluationError, ValueError) as exc:
            return {"error": str(exc), "status": AdvisoryStatus.INTERNAL_ERROR}
        except Exception as exc:  # pragma: no cover - defensive boundary
            return {"error": str(exc), "status": AdvisoryStatus.INTERNAL_ERROR}

    def intent_failure_node(state: AdvisoryState) -> dict[str, Any]:
        return _response_update(
            state,
            AdvisoryStatus.INTENT_ERROR,
            "I couldn't interpret that request. Please try rephrasing it.",
        )

    def missing_context_node(state: AdvisoryState) -> dict[str, Any]:
        return _response_update(
            state,
            AdvisoryStatus.MISSING_CONTEXT,
            "Please provide a location so I can check the relevant weather advisory.",
        )

    def location_failure_node(state: AdvisoryState) -> dict[str, Any]:
        return _response_update(
            state,
            AdvisoryStatus.LOCATION_ERROR,
            "I couldn't resolve that location. Please provide a city or a more specific place.",
        )

    def time_failure_node(state: AdvisoryState) -> dict[str, Any]:
        return _response_update(
            state,
            AdvisoryStatus.TIME_ERROR,
            "I couldn't resolve the requested time. Please try a time such as now, tonight, or tomorrow morning.",
        )

    def no_applicable_policy_node(state: AdvisoryState) -> dict[str, Any]:
        if state.user_context.unsupported_activity is not None:
            activity = state.user_context.unsupported_activity
            message = (
                f"The current SOP set does not cover {activity}, so I can't provide "
                "policy-grounded weather advice for that activity."
            )
        else:
            message = (
                "The current SOP set does not sufficiently cover this activity and "
                "audience for policy-grounded advice."
            )
        return _response_update(
            state,
            AdvisoryStatus.NO_APPLICABLE_POLICY,
            message,
        )

    def weather_failure_node(state: AdvisoryState) -> dict[str, Any]:
        return _response_update(
            state,
            AdvisoryStatus.WEATHER_ERROR,
            "Weather data is currently unavailable for that place and time. Please try again shortly.",
        )

    def no_policy_match_node(state: AdvisoryState) -> dict[str, Any]:
        return _response_update(
            state,
            AdvisoryStatus.NO_POLICY_MATCH,
            "No configured SOP threshold is currently triggered for this request.",
        )

    def build_advisory_node(state: AdvisoryState) -> dict[str, Any]:
        primary = state.matched_policies[0]
        message = f"{primary.title} ({primary.severity.value}). {primary.guidance}"
        return _response_update(state, AdvisoryStatus.SUCCESS, message)

    def internal_failure_node(state: AdvisoryState) -> dict[str, Any]:
        return _response_update(
            state,
            AdvisoryStatus.INTERNAL_ERROR,
            "The advisory could not be completed because of an internal configuration error.",
        )

    def route_after_intent(state: AdvisoryState) -> str:
        if state.status == AdvisoryStatus.INTENT_ERROR:
            return "intent_failure"
        if state.status == AdvisoryStatus.INTERNAL_ERROR:
            return "internal_failure"
        return "merge_context"

    def route_after_validation(state: AdvisoryState) -> str:
        return (
            "missing_context"
            if state.status == AdvisoryStatus.MISSING_CONTEXT
            else "resolve_location"
        )

    def route_after_location(state: AdvisoryState) -> str:
        if state.status == AdvisoryStatus.LOCATION_ERROR:
            return "location_failure"
        if state.status == AdvisoryStatus.INTERNAL_ERROR:
            return "internal_failure"
        return "resolve_time"

    def route_after_time(state: AdvisoryState) -> str:
        if state.status == AdvisoryStatus.TIME_ERROR:
            return "time_failure"
        if state.status == AdvisoryStatus.INTERNAL_ERROR:
            return "internal_failure"
        return "build_evidence_plan"

    def route_after_plan(state: AdvisoryState) -> str:
        if state.status == AdvisoryStatus.INTERNAL_ERROR:
            return "internal_failure"
        if not state.evidence_plan.candidate_policy_ids:
            return "no_applicable_policy"
        return "fetch_weather"

    def route_after_weather(state: AdvisoryState) -> str:
        if state.status == AdvisoryStatus.WEATHER_ERROR:
            return "weather_failure"
        if state.status == AdvisoryStatus.INTERNAL_ERROR:
            return "internal_failure"
        return "evaluate_policies"

    def route_after_evaluation(state: AdvisoryState) -> str:
        if state.status == AdvisoryStatus.INTERNAL_ERROR:
            return "internal_failure"
        if not state.matched_policies:
            return "no_policy_match"
        return "build_advisory"

    builder = StateGraph(AdvisoryState)
    nodes = {
        "extract_intent": extract_intent_node,
        "merge_context": merge_context_node,
        "validate_context": validate_context_node,
        "resolve_location": resolve_location_node,
        "resolve_time": resolve_time_node,
        "build_evidence_plan": build_evidence_plan_node,
        "fetch_weather": fetch_weather_node,
        "evaluate_policies": evaluate_policies_node,
        "intent_failure": intent_failure_node,
        "missing_context": missing_context_node,
        "location_failure": location_failure_node,
        "time_failure": time_failure_node,
        "no_applicable_policy": no_applicable_policy_node,
        "weather_failure": weather_failure_node,
        "no_policy_match": no_policy_match_node,
        "build_advisory": build_advisory_node,
        "internal_failure": internal_failure_node,
    }
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "extract_intent")
    builder.add_conditional_edges("extract_intent", route_after_intent)
    builder.add_edge("merge_context", "validate_context")
    builder.add_conditional_edges("validate_context", route_after_validation)
    builder.add_conditional_edges("resolve_location", route_after_location)
    builder.add_conditional_edges("resolve_time", route_after_time)
    builder.add_conditional_edges("build_evidence_plan", route_after_plan)
    builder.add_conditional_edges("fetch_weather", route_after_weather)
    builder.add_conditional_edges("evaluate_policies", route_after_evaluation)

    for terminal in (
        "intent_failure",
        "missing_context",
        "location_failure",
        "time_failure",
        "no_applicable_policy",
        "weather_failure",
        "no_policy_match",
        "build_advisory",
        "internal_failure",
    ):
        builder.add_edge(terminal, END)

    if checkpointer is None:
        checkpoint_types = (
            AdvisoryResponse,
            AdvisoryStatus,
            ConditionTrace,
            ConditionTraceKind,
            ConditionTraceStatus,
            EvidencePlan,
            EvidenceRequirement,
            EvaluationStatus,
            IntentUpdate,
            PolicyMatch,
            PolicyEvaluation,
            ResolvedLocation,
            Severity,
            TimeReference,
            TimeReferenceKind,
            UserContext,
            WeatherFacts,
        )
        serde = JsonPlusSerializer(allowed_msgpack_modules=checkpoint_types)
        checkpointer = InMemorySaver(serde=serde)
    return builder.compile(checkpointer=checkpointer)


__all__ = ["create_graph"]
