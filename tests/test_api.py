from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.src.geocoding import LocationResolutionError
from backend.src.graph import create_graph
from backend.src.models import (
    IntentUpdate,
    ResolvedLocation,
    TimeReference,
    TimeReferenceKind,
    WeatherFacts,
)
from backend.src.weather import WeatherServiceError


FIXED_NOW = datetime(2026, 9, 22, 10, 30, tzinfo=timezone.utc)


def cycling_intent(**changes):
    values = {
        "location": "Bhopal",
        "activity": "cycling",
        "unsupported_activity": None,
        "audience": "adult",
        "time_reference": TimeReference(kind=TimeReferenceKind.NOW),
    }
    values.update(changes)
    return IntentUpdate(**values)


def intent_stub(updates):
    async def extract(message, policies, previous_context):
        return updates[message] if isinstance(updates, dict) else updates

    return extract


async def geocode_stub(query):
    if query == "Atlantis":
        raise LocationResolutionError("not found")
    return ResolvedLocation(
        query=query,
        name=query,
        admin1="Madhya Pradesh",
        country="India",
        latitude=23.2599,
        longitude=77.4126,
        timezone="Asia/Kolkata",
    )


def weather_stub(wind_speed=46.2):
    async def fetch(resolved_location, plan, target_time):
        return WeatherFacts(
            wind_speed_kmh=wind_speed,
            latitude=resolved_location.latitude,
            longitude=resolved_location.longitude,
            timezone=resolved_location.timezone,
            observed_at=target_time,
        )

    return fetch


def graph_for(updates, *, weather=None, location_resolver=geocode_stub):
    return create_graph(
        intent_extractor=intent_stub(updates),
        location_resolver=location_resolver,
        weather_fetcher=weather or weather_stub(),
        clock=lambda: FIXED_NOW,
    )


@contextmanager
def client_for(graph):
    previous = getattr(app.state, "graph", None)
    app.state.graph = graph
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.state.graph = previous


def post(client, message="request", session_id="session-1"):
    return client.post("/chat", json={"message": message, "session_id": session_id})


def test_health_still_works():
    graph = graph_for(cycling_intent())
    with client_for(graph) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_success_serializes_weather_and_policy_trace_exactly():
    graph = graph_for(cycling_intent())
    with client_for(graph) as client:
        response = post(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["weather"]["wind_speed_kmh"] == 46.2
    assert body["resolved_location"]["name"] == "Bhopal"
    assert body["candidate_policy_ids"] == ["SOP-WIND-CYCLING-01"]
    assert body["matched_policies"][0]["policy_id"] == "SOP-WIND-CYCLING-01"
    trace = body["policy_evaluations"][0]["condition_trace"]
    assert trace["field"] == "wind_speed_kmh"
    assert trace["actual_value"] == 46.2
    assert trace["operator"] == "gt"
    assert trace["expected_value"] == 40
    assert trace["result"] is True
    assert trace["margin"] == pytest.approx(6.2)


def test_empty_message_is_rejected():
    graph = graph_for(cycling_intent())
    with client_for(graph) as client:
        response = client.post(
            "/chat", json={"message": "   ", "session_id": "session-1"}
        )
    assert response.status_code == 422


def test_empty_session_id_is_rejected():
    graph = graph_for(cycling_intent())
    with client_for(graph) as client:
        response = client.post(
            "/chat", json={"message": "Can I cycle?", "session_id": ""}
        )
    assert response.status_code == 422


def test_same_session_preserves_context_and_different_session_is_isolated():
    graph = graph_for({
        "first": cycling_intent(),
        "follow-up": IntentUpdate(
            time_reference=TimeReference(kind=TimeReferenceKind.TOMORROW_MORNING)
        ),
    })
    with client_for(graph) as client:
        first = post(client, "first", "shared")
        follow_up = post(client, "follow-up", "shared")
        isolated = post(client, "follow-up", "other")

    assert first.json()["status"] == "success"
    assert follow_up.json()["resolved_context"] == {
        "location": "Bhopal",
        "activity": "cycling",
        "unsupported_activity": None,
        "audience": "adult",
        "timeframe": "tomorrow_morning",
    }
    assert isolated.json()["status"] == "missing_context"
    assert isolated.json()["resolved_context"]["location"] is None


def test_no_policy_match_serializes_evaluation_without_matches():
    graph = graph_for(cycling_intent(), weather=weather_stub(wind_speed=20))
    with client_for(graph) as client:
        response = post(client)

    body = response.json()
    assert body["status"] == "no_policy_match"
    assert "safe" not in body["message"].lower()
    assert body["weather"]["wind_speed_kmh"] == 20
    assert body["matched_policies"] == []
    assert body["policy_evaluations"][0]["matched"] is False


def test_missing_context_serializes_without_evidence():
    graph = graph_for(IntentUpdate(activity="cycling"))
    with client_for(graph) as client:
        response = post(client)

    body = response.json()
    assert body["status"] == "missing_context"
    assert body["resolved_location"] is None
    assert body["weather"] is None
    assert body["candidate_policy_ids"] == []
    assert body["policy_evaluations"] == []
    assert body["matched_policies"] == []


def test_location_error_serializes_without_weather():
    graph = graph_for(cycling_intent(location="Atlantis"))
    with client_for(graph) as client:
        response = post(client)

    body = response.json()
    assert body["status"] == "location_error"
    assert body["resolved_location"] is None
    assert body["weather"] is None


def test_weather_error_serializes_without_weather_or_evaluations():
    async def fail_weather(resolved_location, plan, target_time):
        raise WeatherServiceError("provider unavailable")

    graph = graph_for(cycling_intent(), weather=fail_weather)
    with client_for(graph) as client:
        response = post(client)

    body = response.json()
    assert body["status"] == "weather_error"
    assert body["weather"] is None
    assert body["candidate_policy_ids"] == ["SOP-WIND-CYCLING-01"]
    assert body["policy_evaluations"] == []
    assert body["matched_policies"] == []


def test_success_then_early_failure_does_not_leak_stale_evidence():
    graph = graph_for({
        "success": cycling_intent(),
        "failure": IntentUpdate(location="Atlantis"),
    })
    with client_for(graph) as client:
        success = post(client, "success", "stale-check")
        failure = post(client, "failure", "stale-check")

    assert success.json()["weather"]["wind_speed_kmh"] == 46.2
    assert success.json()["matched_policies"]
    body = failure.json()
    assert body["status"] == "location_error"
    assert body["resolved_context"]["location"] == "Atlantis"
    assert body["resolved_context"]["activity"] == "cycling"
    assert body["weather"] is None
    assert body["matched_policies"] == []
    assert body["policy_evaluations"] == []
    assert body["candidate_policy_ids"] == []


def test_unexpected_graph_failure_returns_clean_server_error():
    class FailingGraph:
        async def ainvoke(self, state, config):
            raise RuntimeError("sensitive internal failure")

    with client_for(FailingGraph()) as client:
        response = post(client)

    assert response.status_code == 500
    assert response.json() == {
        "detail": "The advisory service could not complete the request."
    }
    assert "sensitive" not in response.text


def test_endpoint_passes_only_current_turn_and_uses_session_as_thread_id():
    class CapturingGraph:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, state, config):
            self.calls.append((state, config))
            return await graph_for(cycling_intent()).ainvoke(state, config=config)

    graph = CapturingGraph()
    with client_for(graph) as client:
        response = post(client, "current message", "opaque-session")

    assert response.status_code == 200
    state, config = graph.calls[0]
    assert state == {
        "latest_user_message": "current message",
        "session_id": "opaque-session",
    }
    assert config == {"configurable": {"thread_id": "opaque-session"}}


def test_one_graph_instance_is_reused_across_requests():
    class CountingGraph:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.calls = 0

        async def ainvoke(self, state, config):
            self.calls += 1
            return await self.wrapped.ainvoke(state, config=config)

    graph = CountingGraph(graph_for(cycling_intent()))
    with client_for(graph) as client:
        post(client, session_id="one")
        post(client, session_id="two")
        assert app.state.graph is graph

    assert graph.calls == 2
