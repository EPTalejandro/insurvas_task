import httpx
import pytest

from app.httpclient import ApiError, get_json


def client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_returns_json_on_success():
    client = client_with(lambda request: httpx.Response(200, json={"items": [1, 2]}))
    assert get_json(client, "https://api.test/x") == {"items": [1, 2]}


def test_retries_rate_limit_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"ok": True})

    result = get_json(client_with(handler), "https://api.test/x", backoff_s=0)
    assert result == {"ok": True}
    assert len(calls) == 2


def test_client_error_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, text="forbidden")

    with pytest.raises(ApiError) as info:
        get_json(client_with(handler), "https://api.test/x", backoff_s=0)
    assert info.value.status_code == 403
    assert len(calls) == 1


def test_gives_up_after_retries_and_hides_the_url():
    def handler(request):
        return httpx.Response(503, text="unavailable")

    with pytest.raises(ApiError) as info:
        get_json(client_with(handler), "https://api.test/x?key=SECRET", retries=2, backoff_s=0)
    assert info.value.status_code == 503
    assert "SECRET" not in str(info.value)


def test_network_errors_are_retried_then_reported_as_api_errors():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectTimeout("boom", request=request)

    with pytest.raises(ApiError) as info:
        get_json(client_with(handler), "https://api.test/x?key=SECRET", retries=2, backoff_s=0)
    assert len(calls) == 3
    assert info.value.status_code == 0
    assert "SECRET" not in str(info.value)
