import asyncio

import httpx
import pytest

from backend.src.geocoding import LocationResolutionError, resolve_location


def run(coroutine):
    return asyncio.run(coroutine)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_bhopal_response_is_normalized():
    def handler(request):
        assert request.url.params["name"] == "Bhopal"
        assert request.url.params["count"] == "5"
        return httpx.Response(200, json={"results": [{
            "name": "Bhopal",
            "admin1": "Madhya Pradesh",
            "country": "India",
            "latitude": 23.25469,
            "longitude": 77.40289,
            "timezone": "Asia/Kolkata",
        }]})

    async def scenario():
        async with client_for(handler) as client:
            return await resolve_location(" Bhopal ", client)

    location = run(scenario())
    assert location.query == "Bhopal"
    assert location.name == "Bhopal"
    assert location.admin1 == "Madhya Pradesh"
    assert location.country == "India"
    assert location.timezone == "Asia/Kolkata"


def test_empty_query_is_rejected_without_a_request():
    with pytest.raises(LocationResolutionError, match="cannot be empty"):
        run(resolve_location("   "))


def test_no_results_is_clear():
    async def scenario():
        async with client_for(lambda request: httpx.Response(200, json={"results": []})) as client:
            return await resolve_location("Not a real location", client)

    with pytest.raises(LocationResolutionError, match="No location found"):
        run(scenario())


def test_timeout_is_clear():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    async def scenario():
        async with client_for(handler) as client:
            return await resolve_location("Bhopal", client)

    with pytest.raises(LocationResolutionError, match="timed out"):
        run(scenario())


def test_http_failure_is_clear():
    async def scenario():
        async with client_for(lambda request: httpx.Response(503)) as client:
            return await resolve_location("Bhopal", client)

    with pytest.raises(LocationResolutionError, match="HTTP 503"):
        run(scenario())


@pytest.mark.parametrize("result", [
    {"name": "Bhopal", "country": "India", "longitude": 77.4, "timezone": "Asia/Kolkata"},
    {"name": "Bhopal", "country": "India", "latitude": 23.2, "longitude": 77.4},
])
def test_incomplete_result_is_rejected(result):
    async def scenario():
        async with client_for(
            lambda request: httpx.Response(200, json={"results": [result]})
        ) as client:
            return await resolve_location("Bhopal", client)

    with pytest.raises(LocationResolutionError, match="missing required location data"):
        run(scenario())


def test_transport_error_is_clear():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    async def scenario():
        async with client_for(handler) as client:
            return await resolve_location("Bhopal", client)

    with pytest.raises(LocationResolutionError, match="network error"):
        run(scenario())


def test_malformed_json_is_rejected():
    async def scenario():
        async with client_for(lambda request: httpx.Response(200, content=b"not-json")) as client:
            return await resolve_location("Bhopal", client)

    with pytest.raises(LocationResolutionError, match="malformed JSON"):
        run(scenario())
