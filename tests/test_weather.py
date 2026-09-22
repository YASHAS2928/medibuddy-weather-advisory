import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from backend.src.evidence_planner import build_evidence_plan
from backend.src.models import EvidencePlan, EvidenceRequirement, ResolvedLocation, UserContext
from backend.src.policy_loader import load_policies
from backend.src.weather import (
    OPEN_METEO_FIELD_MAP,
    WeatherDataError,
    WeatherServiceError,
    fetch_weather,
    select_hourly_index,
)


TARGET = datetime(2026, 9, 22, 9, 10, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def location() -> ResolvedLocation:
    return ResolvedLocation(
        query="Bhopal",
        name="Bhopal",
        admin1="Madhya Pradesh",
        country="India",
        latitude=23.25469,
        longitude=77.40289,
        timezone="Asia/Kolkata",
    )


def run(coroutine):
    return asyncio.run(coroutine)


def plan_for(*fields: str) -> EvidencePlan:
    return EvidencePlan(requirements=[
        EvidenceRequirement(
            field=field,
            required_by=["SOP-TEST-01"],
            reason="Required for test policy.",
        )
        for field in fields
    ])


def forecast_payload(**hourly_fields) -> dict:
    return {
        "latitude": 23.25,
        "longitude": 77.375,
        "timezone": "Asia/Kolkata",
        "hourly": {
            "time": [
                "2026-09-22T08:00",
                "2026-09-22T09:00",
                "2026-09-22T10:00",
            ],
            **hourly_fields,
        },
    }


def fetch_with_payload(location, plan, payload, target=TARGET, inspect=None):
    def handler(request):
        if inspect:
            inspect(request)
        return httpx.Response(200, json=payload)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_weather(location, plan, target, client)

    return run(scenario())


def test_field_mapping_is_complete_for_policy_weather_fields():
    assert OPEN_METEO_FIELD_MAP == {
        "temperature_c": "temperature_2m",
        "apparent_temperature_c": "apparent_temperature",
        "precipitation_mm": "precipitation",
        "precipitation_probability": "precipitation_probability",
        "wind_speed_kmh": "wind_speed_10m",
        "wind_gust_kmh": "wind_gusts_10m",
        "uv_index": "uv_index",
        "weather_code": "weather_code",
        "visibility_m": "visibility",
    }


def test_single_field_request_has_no_fixed_giant_payload(location):
    def inspect(request):
        assert request.url.params["hourly"] == "wind_speed_10m"
        assert "visibility" not in request.url.params["hourly"]
        assert "uv_index" not in request.url.params["hourly"]

    weather = fetch_with_payload(
        location,
        plan_for("wind_speed_kmh"),
        forecast_payload(wind_speed_10m=[12.0, 14.5, 18.0]),
        inspect=inspect,
    )
    assert weather.wind_speed_kmh == 14.5
    assert weather.visibility_m is None
    assert weather.uv_index is None


def test_multiple_fields_are_mapped_and_units_are_explicit(location):
    def inspect(request):
        assert request.url.params["hourly"] == (
            "precipitation_probability,wind_speed_10m"
        )
        assert request.url.params["temperature_unit"] == "celsius"
        assert request.url.params["wind_speed_unit"] == "kmh"
        assert request.url.params["precipitation_unit"] == "mm"
        assert request.url.params["start_date"] == "2026-09-22"
        assert request.url.params["end_date"] == "2026-09-22"
        assert "apikey" not in request.url.params

    weather = fetch_with_payload(
        location,
        plan_for("wind_speed_kmh", "precipitation_probability"),
        forecast_payload(
            wind_speed_10m=[12.0, 14.5, 18.0],
            precipitation_probability=[10, 35, 60],
        ),
        inspect=inspect,
    )
    assert weather.wind_speed_kmh == 14.5
    assert weather.precipitation_probability == 35


def test_nearest_hour_selects_0900_for_0910():
    times = ["2026-09-22T08:00", "2026-09-22T09:00", "2026-09-22T10:00"]
    assert select_hourly_index(times, TARGET, "Asia/Kolkata") == 1


def test_nearest_hour_selects_1000_for_0940():
    times = ["2026-09-22T08:00", "2026-09-22T09:00", "2026-09-22T10:00"]
    target = datetime(2026, 9, 22, 9, 40, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert select_hourly_index(times, target, "Asia/Kolkata") == 2


def test_nearest_hour_tie_selects_earlier_point():
    times = ["2026-09-22T09:00", "2026-09-22T10:00"]
    target = datetime(2026, 9, 22, 9, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert select_hourly_index(times, target, "Asia/Kolkata") == 0


def test_naive_target_is_rejected(location):
    target = datetime(2026, 9, 22, 9, 10)
    with pytest.raises(WeatherDataError, match="timezone-aware"):
        run(fetch_weather(location, plan_for("wind_speed_kmh"), target))


def test_all_fields_normalize_with_expected_units(location):
    plan = plan_for(*OPEN_METEO_FIELD_MAP)
    weather = fetch_with_payload(
        location,
        plan,
        forecast_payload(
            temperature_2m=[22.0, 23.5, 25.0],
            apparent_temperature=[23.0, 24.5, 26.0],
            precipitation=[0.0, 1.2, 2.0],
            precipitation_probability=[10, 40, 70],
            wind_speed_10m=[10.0, 15.5, 20.0],
            wind_gusts_10m=[20.0, 28.0, 35.0],
            uv_index=[1.0, 3.2, 5.0],
            weather_code=[1, 61, 63],
            visibility=[10000.0, 8000.0, 6000.0],
        ),
    )
    assert weather.model_dump(exclude_none=True) == {
        "temperature_c": 23.5,
        "apparent_temperature_c": 24.5,
        "precipitation_mm": 1.2,
        "precipitation_probability": 40.0,
        "wind_speed_kmh": 15.5,
        "wind_gust_kmh": 28.0,
        "uv_index": 3.2,
        "weather_code": 61,
        "visibility_m": 8000.0,
        "latitude": 23.25,
        "longitude": 77.375,
        "timezone": "Asia/Kolkata",
        "observed_at": datetime(2026, 9, 22, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
    }


def test_legitimate_null_measurement_remains_missing(location):
    weather = fetch_with_payload(
        location,
        plan_for("wind_speed_kmh"),
        forecast_payload(wind_speed_10m=[12.0, None, 18.0]),
    )
    assert weather.wind_speed_kmh is None


@pytest.mark.parametrize("payload, message", [
    ({"latitude": 23.2, "longitude": 77.4, "timezone": "Asia/Kolkata"}, "hourly data block"),
    ({
        "latitude": 23.2,
        "longitude": 77.4,
        "timezone": "Asia/Kolkata",
        "hourly": {"wind_speed_10m": [1, 2, 3]},
    }, "hourly time array"),
    (forecast_payload(wind_speed_10m=[1, 2]), "does not align"),
])
def test_malformed_hourly_data_fails(location, payload, message):
    with pytest.raises(WeatherDataError, match=message):
        fetch_with_payload(location, plan_for("wind_speed_kmh"), payload)


def test_requested_hourly_field_missing_fails(location):
    with pytest.raises(WeatherDataError, match="missing hourly field 'wind_speed_10m'"):
        fetch_with_payload(location, plan_for("wind_speed_kmh"), forecast_payload())


def test_invalid_response_timezone_fails(location):
    payload = forecast_payload(wind_speed_10m=[12, 14, 18])
    payload["timezone"] = "Not/A_Timezone"
    with pytest.raises(WeatherDataError, match="Invalid timezone"):
        fetch_with_payload(location, plan_for("wind_speed_kmh"), payload)


def test_target_outside_forecast_fails(location):
    target = datetime(2026, 9, 22, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    with pytest.raises(WeatherDataError, match="outside the returned forecast range"):
        fetch_with_payload(
            location,
            plan_for("wind_speed_kmh"),
            forecast_payload(wind_speed_10m=[12, 14, 18]),
            target,
        )


def test_timeout_fails_without_weather(location):
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_weather(location, plan_for("wind_speed_kmh"), TARGET, client)

    with pytest.raises(WeatherServiceError, match="timed out"):
        run(scenario())


def test_http_failure_is_clear(location):
    async def scenario():
        transport = httpx.MockTransport(lambda request: httpx.Response(500))
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_weather(location, plan_for("wind_speed_kmh"), TARGET, client)

    with pytest.raises(WeatherServiceError, match="HTTP 500"):
        run(scenario())


def test_transport_failure_is_clear(location):
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_weather(location, plan_for("wind_speed_kmh"), TARGET, client)

    with pytest.raises(WeatherServiceError, match="network error"):
        run(scenario())


def test_malformed_json_is_rejected(location):
    async def scenario():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"not-json")
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_weather(location, plan_for("wind_speed_kmh"), TARGET, client)

    with pytest.raises(WeatherDataError, match="malformed JSON"):
        run(scenario())


def test_unsupported_provider_mapping_is_clear(location):
    with pytest.raises(WeatherDataError, match="mapping.*'observed_at'"):
        run(fetch_weather(location, plan_for("observed_at"), TARGET))


def test_real_cycling_evidence_plan_controls_request(location):
    plan = build_evidence_plan(
        UserContext(location="Bhopal", activity="cycling", audience="adult", timeframe="today"),
        load_policies(),
    )

    def inspect(request):
        assert request.url.params["hourly"] == "wind_speed_10m"

    weather = fetch_with_payload(
        location,
        plan,
        forecast_payload(wind_speed_10m=[32.0, 46.2, 38.0]),
        inspect=inspect,
    )
    assert plan.candidate_policy_ids == ["SOP-WIND-CYCLING-01"]
    assert [item.field for item in plan.requirements] == ["wind_speed_kmh"]
    assert weather.wind_speed_kmh == 46.2
    assert weather.visibility_m is None
