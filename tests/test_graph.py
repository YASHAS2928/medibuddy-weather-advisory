import asyncio
from datetime import datetime, timezone

from backend.src.geocoding import LocationResolutionError
from backend.src.graph import create_graph
from backend.src.intent import IntentExtractionError
from backend.src.models import (
    AdvisoryStatus,
    IntentUpdate,
    ResolvedLocation,
    TimeReference,
    TimeReferenceKind,
    WeatherFacts,
)
from backend.src.policies import SOP
from backend.src.policy_loader import load_policies
from backend.src.weather import WeatherServiceError


FIXED_NOW = datetime(2026, 9, 22, 10, 30, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


def location(name: str = "Bhopal", timezone_name: str = "Asia/Kolkata"):
    return ResolvedLocation(
        query=name,
        name=name,
        admin1="Madhya Pradesh",
        country="India",
        latitude=23.2599,
        longitude=77.4126,
        timezone=timezone_name,
    )


def intent_stub(updates):
    async def extract(message, policies, previous_context):
        value = updates[message] if isinstance(updates, dict) else updates
        if isinstance(value, Exception):
            raise value
        return value

    return extract


async def geocode_stub(query):
    return location(query)


def weather_stub(**overrides):
    defaults = {
        "temperature_c": 25,
        "apparent_temperature_c": 25,
        "precipitation_mm": 0,
        "precipitation_probability": 0,
        "wind_speed_kmh": 10,
        "wind_gust_kmh": 15,
        "uv_index": 2,
        "weather_code": 0,
        "visibility_m": 10_000,
    }

    async def fetch(resolved_location, plan, target_time):
        fields = {item.field for item in plan.requirements}
        values = {field: defaults[field] for field in fields}
        values.update(overrides)
        return WeatherFacts(
            **values,
            latitude=resolved_location.latitude,
            longitude=resolved_location.longitude,
            timezone=resolved_location.timezone,
            observed_at=target_time,
        )

    return fetch


def invoke(graph, message="request", thread_id="thread-1"):
    return run(graph.ainvoke(
        {"latest_user_message": message, "session_id": thread_id},
        config={"configurable": {"thread_id": thread_id}},
    ))


def policy(
    policy_id,
    *,
    activity,
    audience="general",
    field="wind_speed_kmh",
    operator="gte",
    value=30,
    severity="HIGH",
    priority=50,
    guidance="Change the plan.",
):
    return SOP.model_validate({
        "id": policy_id,
        "title": f"Policy {policy_id}",
        "category": "outdoor_activity",
        "severity": severity,
        "priority": priority,
        "applies_to": {"activities": [activity], "audiences": [audience]},
        "conditions": {"field": field, "operator": operator, "value": value},
        "guidance": guidance,
    })


def cycling_intent(**changes):
    values = {
        "location": "Bhopal",
        "activity": "cycling",
        "audience": "adult",
        "time_reference": TimeReference(kind=TimeReferenceKind.NOW),
    }
    values.update(changes)
    return IntentUpdate(**values)


def test_success_path_uses_real_planner_and_policy_engine():
    graph = create_graph(
        intent_extractor=intent_stub(cycling_intent()),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(wind_speed_kmh=46.2),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["status"] == AdvisoryStatus.SUCCESS
    assert [match.policy_id for match in result["matched_policies"]] == [
        "SOP-WIND-CYCLING-01"
    ]
    assert result["response"].message.endswith(
        "Consider postponing cycling until wind conditions improve."
    )
    assert result["evidence_plan"].candidate_policy_ids == [
        "SOP-WIND-CYCLING-01"
    ]
    assert [item.field for item in result["evidence_plan"].requirements] == [
        "wind_speed_kmh"
    ]
    assert result["policy_evaluations"][0].matched is True


def test_nonmatching_evidence_is_not_reported_as_safe():
    graph = create_graph(
        intent_extractor=intent_stub(cycling_intent()),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(wind_speed_kmh=20),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["status"] == AdvisoryStatus.NO_POLICY_MATCH
    assert result["matched_policies"] == []
    assert "safe" not in result["response"].message.lower()
    assert result["policy_evaluations"][0].matched is False


def test_missing_location_stops_before_geocoding():
    calls = []

    async def geocode(query):
        calls.append(query)
        return location(query)

    graph = create_graph(
        intent_extractor=intent_stub(IntentUpdate(activity="cycling")),
        location_resolver=geocode,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["status"] == AdvisoryStatus.MISSING_CONTEXT
    assert calls == []


def test_fresh_session_generic_venue_remains_missing_location():
    calls = []

    async def geocode(query):
        calls.append(query)
        return location(query)

    graph = create_graph(
        intent_extractor=intent_stub(IntentUpdate(
            activity="picnic",
            audience="general",
            time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW),
        )),
        location_resolver=geocode,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(
        graph,
        message="Can my family have lunch at the park tomorrow?",
        thread_id="fresh-venue-session",
    )

    assert result["status"] == AdvisoryStatus.MISSING_CONTEXT
    assert result["user_context"].location is None
    assert result["user_context"].activity == "picnic"
    assert calls == []


def test_bad_location_returns_location_error():
    async def fail_geocode(query):
        raise LocationResolutionError("not found")

    graph = create_graph(
        intent_extractor=intent_stub(cycling_intent(location="Atlantis")),
        location_resolver=fail_geocode,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["status"] == AdvisoryStatus.LOCATION_ERROR
    assert result["weather"] is None


def test_time_failure_has_a_distinct_status():
    async def bad_timezone(query):
        return location(query, timezone_name="Mars/Olympus")

    graph = create_graph(
        intent_extractor=intent_stub(cycling_intent()),
        location_resolver=bad_timezone,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["status"] == AdvisoryStatus.TIME_ERROR
    assert result["target_time"] is None


def test_weather_failure_returns_weather_error():
    async def fail_weather(resolved_location, plan, target_time):
        raise WeatherServiceError("provider unavailable")

    graph = create_graph(
        intent_extractor=intent_stub(cycling_intent()),
        location_resolver=geocode_stub,
        weather_fetcher=fail_weather,
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["status"] == AdvisoryStatus.WEATHER_ERROR
    assert result["response"].weather is None


def test_no_applicable_policy_skips_weather():
    policies = [
        policy("SOP-CYCLE-ELDERLY-01", activity="cycling", audience="elderly"),
        policy("SOP-WALK-ADULT-01", activity="walking", audience="adult"),
    ]
    weather_calls = []

    async def weather(resolved_location, plan, target_time):
        weather_calls.append(plan)
        return WeatherFacts(wind_speed_kmh=50)

    graph = create_graph(
        policies=policies,
        intent_extractor=intent_stub(cycling_intent()),
        location_resolver=geocode_stub,
        weather_fetcher=weather,
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["status"] == AdvisoryStatus.NO_APPLICABLE_POLICY
    assert result["evidence_plan"].candidate_policy_ids == []
    assert weather_calls == []


def test_uncovered_activity_has_no_candidates_and_skips_weather():
    weather_calls = []

    async def weather(resolved_location, plan, target_time):
        weather_calls.append(plan)
        return WeatherFacts()

    graph = create_graph(
        intent_extractor=intent_stub(IntentUpdate(
            location="Bhopal",
            unsupported_activity="swimming",
            audience="adult",
            time_reference=TimeReference(kind=TimeReferenceKind.NOW),
        )),
        location_resolver=geocode_stub,
        weather_fetcher=weather,
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph, "Can I go swimming in Bhopal now?", "swimming")

    assert result["status"] == AdvisoryStatus.NO_APPLICABLE_POLICY
    assert result["user_context"].activity is None
    assert result["user_context"].unsupported_activity == "swimming"
    assert result["evidence_plan"].candidate_policy_ids == []
    assert result["evidence_plan"].requirements == []
    assert result["weather"] is None
    assert weather_calls == []
    assert "does not cover swimming" in result["response"].message
    assert "safe" not in result["response"].message.lower()


def test_uncovered_activity_behavior_is_generic():
    graph = create_graph(
        intent_extractor=intent_stub(IntentUpdate(
            location="Bhopal",
            unsupported_activity="skateboarding",
            time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW),
        )),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph, "Can I skateboard in Bhopal tomorrow?", "skateboard")

    assert result["status"] == AdvisoryStatus.NO_APPLICABLE_POLICY
    assert result["user_context"].unsupported_activity == "skateboarding"
    assert result["evidence_plan"].candidate_policy_ids == []


def test_multiple_matches_are_preserved_in_deterministic_order():
    policies = load_policies() + [
        policy(
            "SOP-WIND-CYCLING-SEVERE-01",
            activity="cycling",
            audience="adult",
            value=45,
            severity="SEVERE",
            priority=90,
            guidance="Do not cycle until winds ease.",
        )
    ]
    graph = create_graph(
        policies=policies,
        intent_extractor=intent_stub(cycling_intent()),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(wind_speed_kmh=46.2),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert [match.policy_id for match in result["matched_policies"]] == [
        "SOP-WIND-CYCLING-SEVERE-01",
        "SOP-WIND-CYCLING-01",
    ]
    assert result["response"].matched_policies == result["matched_policies"]


def test_follow_up_reuses_checkpointed_context_in_same_thread():
    updates = {
        "first": cycling_intent(
            time_reference=TimeReference(kind=TimeReferenceKind.TONIGHT)
        ),
        "follow-up": IntentUpdate(
            time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW_MORNING)
        ),
    }
    graph = create_graph(
        intent_extractor=intent_stub(updates),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    invoke(graph, "first", "conversation")
    result = invoke(graph, "follow-up", "conversation")

    assert result["user_context"].location == "Bhopal"
    assert result["user_context"].activity == "cycling"
    assert result["user_context"].timeframe == "tomorrow_morning"
    assert result["target_time"].hour == 9
    assert result["target_time"].date().isoformat() == "2026-09-23"


def test_lunch_follow_up_retains_bhopal_and_resolves_tomorrow_midday():
    updates = {
        "first": cycling_intent(
            time_reference=TimeReference(kind=TimeReferenceKind.TONIGHT)
        ),
        "lunch": IntentUpdate(
            location=None,
            activity="picnic",
            audience="general",
            time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW_MIDDAY),
        ),
    }
    graph = create_graph(
        intent_extractor=intent_stub(updates),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    invoke(graph, "first", "lunch-conversation")
    result = invoke(graph, "lunch", "lunch-conversation")

    assert result["user_context"].location == "Bhopal"
    assert result["user_context"].activity == "picnic"
    assert result["user_context"].audience == "general"
    assert result["user_context"].timeframe == "tomorrow_midday"
    assert result["target_time"].isoformat() == "2026-09-23T13:00:00+05:30"


def test_activity_state_switches_between_supported_and_uncovered():
    updates = {
        "cycling": cycling_intent(),
        "swimming": IntentUpdate(unsupported_activity="swimming"),
        "tomorrow": IntentUpdate(
            time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW_MORNING)
        ),
        "cycling-again": IntentUpdate(activity="cycling"),
    }
    weather_calls = []

    async def weather(resolved_location, plan, target_time):
        weather_calls.append(plan)
        return WeatherFacts(wind_speed_kmh=20)

    graph = create_graph(
        intent_extractor=intent_stub(updates),
        location_resolver=geocode_stub,
        weather_fetcher=weather,
        clock=lambda: FIXED_NOW,
    )

    invoke(graph, "cycling", "activity-switch")
    swimming = invoke(graph, "swimming", "activity-switch")
    tomorrow = invoke(graph, "tomorrow", "activity-switch")
    cycling = invoke(graph, "cycling-again", "activity-switch")

    assert swimming["user_context"].activity is None
    assert swimming["user_context"].unsupported_activity == "swimming"
    assert tomorrow["user_context"].activity is None
    assert tomorrow["user_context"].unsupported_activity == "swimming"
    assert tomorrow["user_context"].timeframe == "tomorrow_morning"
    assert cycling["user_context"].activity == "cycling"
    assert cycling["user_context"].unsupported_activity is None
    assert len(weather_calls) == 2


def test_location_and_activity_changes_replace_only_supplied_context():
    updates = {
        "first": cycling_intent(),
        "move": IntentUpdate(location="Indore"),
        "walk": IntentUpdate(activity="walking"),
    }
    graph = create_graph(
        intent_extractor=intent_stub(updates),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    invoke(graph, "first", "changes")
    moved = invoke(graph, "move", "changes")
    walked = invoke(graph, "walk", "changes")

    assert moved["user_context"].location == "Indore"
    assert moved["user_context"].activity == "cycling"
    assert walked["user_context"].location == "Indore"
    assert walked["user_context"].activity == "walking"
    assert set(walked["evidence_plan"].candidate_policy_ids) == {
        "SOP-RAIN-PREPAREDNESS-01",
        "SOP-THUNDER-OUTDOOR-01",
        "SOP-UV-PROLONGED-OUTDOOR-01",
    }


def test_checkpoints_are_isolated_by_thread_id():
    updates = {
        "first": cycling_intent(),
        "follow-up": IntentUpdate(
            time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW)
        ),
    }
    graph = create_graph(
        intent_extractor=intent_stub(updates),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    invoke(graph, "first", "thread-a")
    isolated = invoke(graph, "follow-up", "thread-b")

    assert isolated["status"] == AdvisoryStatus.MISSING_CONTEXT
    assert isolated["user_context"].location is None


def test_intent_failure_routes_to_a_user_facing_error():
    graph = create_graph(
        intent_extractor=intent_stub(IntentExtractionError("provider failed")),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["status"] == AdvisoryStatus.INTENT_ERROR
    assert "provider failed" not in result["response"].message
    assert result["error"] == "provider failed"


def test_missing_time_defaults_to_injected_clock_deterministically():
    graph = create_graph(
        intent_extractor=intent_stub(cycling_intent(time_reference=None)),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["time_reference"].kind == TimeReferenceKind.NOW
    assert result["user_context"].timeframe == "now"
    assert result["target_time"].isoformat() == "2026-09-22T16:00:00+05:30"


def test_new_sop_flows_through_planner_weather_and_engine_without_graph_changes():
    kayaking = policy(
        "SOP-WIND-KAYAKING-01",
        activity="kayaking",
        value=25,
        severity="MODERATE",
        guidance="Return to shore until winds ease.",
    )
    plans = []

    async def weather(resolved_location, plan, target_time):
        plans.append(plan)
        return WeatherFacts(wind_speed_kmh=30)

    graph = create_graph(
        policies=[kayaking],
        intent_extractor=intent_stub(cycling_intent(activity="kayaking")),
        location_resolver=geocode_stub,
        weather_fetcher=weather,
        clock=lambda: FIXED_NOW,
    )

    result = invoke(graph)

    assert result["status"] == AdvisoryStatus.SUCCESS
    assert plans[0].candidate_policy_ids == ["SOP-WIND-KAYAKING-01"]
    assert result["matched_policies"][0].guidance == "Return to shore until winds ease."


def test_compiled_graph_exposes_meaningful_node_structure():
    graph = create_graph(
        intent_extractor=intent_stub(cycling_intent()),
        location_resolver=geocode_stub,
        weather_fetcher=weather_stub(),
        clock=lambda: FIXED_NOW,
    )

    nodes = set(graph.get_graph().nodes)

    assert {
        "extract_intent",
        "merge_context",
        "validate_context",
        "resolve_location",
        "resolve_time",
        "build_evidence_plan",
        "fetch_weather",
        "evaluate_policies",
        "no_applicable_policy",
        "no_policy_match",
        "build_advisory",
    } <= nodes
    assert "__start__" in nodes
    assert "__end__" in nodes
