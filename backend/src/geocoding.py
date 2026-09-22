import httpx
from pydantic import ValidationError

from backend.src.config import Settings
from backend.src.models import ResolvedLocation


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


class LocationResolutionError(RuntimeError):
    pass


async def resolve_location(
    query: str,
    client: httpx.AsyncClient | None = None,
) -> ResolvedLocation:
    cleaned_query = query.strip()
    if not cleaned_query:
        raise LocationResolutionError("Location query cannot be empty")

    owns_client = client is None
    active_client = client or httpx.AsyncClient()
    try:
        try:
            response = await active_client.get(
                GEOCODING_URL,
                params={
                    "name": cleaned_query,
                    "count": 5,
                    "language": "en",
                    "format": "json",
                },
                timeout=Settings().request_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LocationResolutionError("Location lookup timed out") from exc
        except httpx.RequestError as exc:
            raise LocationResolutionError("Location lookup failed due to a network error") from exc

        if not response.is_success:
            raise LocationResolutionError(
                f"Location service returned HTTP {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LocationResolutionError("Location service returned malformed JSON") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise LocationResolutionError("Location service returned a malformed response")
        if not payload["results"]:
            raise LocationResolutionError(f"No location found for '{cleaned_query}'")

        result = payload["results"][0]
        if not isinstance(result, dict):
            raise LocationResolutionError("Location service returned a malformed result")
        try:
            return ResolvedLocation(
                query=cleaned_query,
                name=result.get("name"),
                admin1=result.get("admin1"),
                country=result.get("country"),
                latitude=result.get("latitude"),
                longitude=result.get("longitude"),
                timezone=result.get("timezone"),
            )
        except ValidationError as exc:
            raise LocationResolutionError(
                "Location service result is missing required location data"
            ) from exc
    finally:
        if owns_client:
            await active_client.aclose()
