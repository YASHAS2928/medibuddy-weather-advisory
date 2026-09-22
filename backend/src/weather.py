from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import ValidationError

from backend.src.config import Settings
from backend.src.models import EvidencePlan, ResolvedLocation, WeatherFacts


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

OPEN_METEO_FIELD_MAP = {
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


class WeatherServiceError(RuntimeError):
    pass


class WeatherDataError(WeatherServiceError):
    pass


async def fetch_weather(
    location: ResolvedLocation,
    evidence_plan: EvidencePlan,
    target_time: datetime,
    client: httpx.AsyncClient | None = None,
) -> WeatherFacts:
    target_local = _target_in_location_timezone(target_time, location.timezone)
    normalized_fields = sorted({item.field for item in evidence_plan.requirements})
    if not normalized_fields:
        raise WeatherDataError("Evidence plan contains no weather requirements")

    provider_fields = []
    for field in normalized_fields:
        provider_field = OPEN_METEO_FIELD_MAP.get(field)
        if provider_field is None:
            raise WeatherDataError(
                f"No Open-Meteo mapping exists for weather field '{field}'"
            )
        provider_fields.append(provider_field)

    request_date = target_local.date().isoformat()
    params = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "hourly": ",".join(sorted(provider_fields)),
        "timezone": location.timezone,
        "start_date": request_date,
        "end_date": request_date,
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    payload = await _request_forecast(params, client)
    return _normalize_weather(
        payload,
        normalized_fields,
        target_local,
    )


def select_hourly_index(
    times: list[str],
    target_time: datetime,
    timezone: str,
) -> int:
    """Select the nearest timestamp, choosing the earlier point when tied."""
    if target_time.tzinfo is None or target_time.utcoffset() is None:
        raise WeatherDataError("Target time must be timezone-aware")
    if not times:
        raise WeatherDataError("Hourly weather data has no timestamps")

    zone = _load_timezone(timezone)
    parsed_times = []
    for value in times:
        parsed_times.append(_parse_hourly_time(value, zone))

    if any(current >= following for current, following in zip(parsed_times, parsed_times[1:])):
        raise WeatherDataError("Hourly weather timestamps must be strictly increasing")

    target_local = target_time.astimezone(zone)
    if target_local < parsed_times[0] or target_local > parsed_times[-1]:
        raise WeatherDataError("Target time is outside the returned forecast range")

    return min(
        range(len(parsed_times)),
        key=lambda index: (abs(parsed_times[index] - target_local), parsed_times[index]),
    )


async def _request_forecast(
    params: dict[str, object],
    client: httpx.AsyncClient | None,
) -> dict:
    owns_client = client is None
    active_client = client or httpx.AsyncClient()
    try:
        try:
            response = await active_client.get(
                FORECAST_URL,
                params=params,
                timeout=Settings().request_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise WeatherServiceError("Weather request timed out") from exc
        except httpx.RequestError as exc:
            raise WeatherServiceError("Weather request failed due to a network error") from exc

        if not response.is_success:
            raise WeatherServiceError(
                f"Weather service returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise WeatherDataError("Weather service returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise WeatherDataError("Weather service returned a malformed response")
        return payload
    finally:
        if owns_client:
            await active_client.aclose()


def _normalize_weather(
    payload: dict,
    normalized_fields: list[str],
    target_time: datetime,
) -> WeatherFacts:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise WeatherDataError("Weather response is missing the hourly data block")
    times = hourly.get("time")
    if not isinstance(times, list):
        raise WeatherDataError("Weather response is missing the hourly time array")

    timezone = payload.get("timezone")
    if not isinstance(timezone, str) or not timezone:
        raise WeatherDataError("Weather response is missing a valid timezone")
    selected_index = select_hourly_index(times, target_time, timezone)

    normalized_values = {}
    for field in normalized_fields:
        provider_field = OPEN_METEO_FIELD_MAP[field]
        values = hourly.get(provider_field)
        if not isinstance(values, list):
            raise WeatherDataError(
                f"Weather response is missing hourly field '{provider_field}'"
            )
        if len(values) != len(times):
            raise WeatherDataError(
                f"Hourly field '{provider_field}' does not align with the time array"
            )
        normalized_values[field] = values[selected_index]

    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if not _is_number(latitude) or not _is_number(longitude):
        raise WeatherDataError("Weather response is missing valid coordinates")

    selected_time = _parse_hourly_time(
        times[selected_index],
        _load_timezone(timezone),
    )
    try:
        return WeatherFacts(
            **normalized_values,
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            observed_at=selected_time,
        )
    except ValidationError as exc:
        raise WeatherDataError("Weather response contains invalid normalized values") from exc


def _target_in_location_timezone(target_time: datetime, timezone: str) -> datetime:
    if target_time.tzinfo is None or target_time.utcoffset() is None:
        raise WeatherDataError("Target time must be timezone-aware")
    return target_time.astimezone(_load_timezone(timezone))


def _load_timezone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise WeatherDataError(f"Invalid timezone '{timezone}'") from exc


def _parse_hourly_time(value: object, timezone: ZoneInfo) -> datetime:
    if not isinstance(value, str):
        raise WeatherDataError("Hourly weather timestamps must be strings")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise WeatherDataError(f"Invalid hourly timestamp '{value}'") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
