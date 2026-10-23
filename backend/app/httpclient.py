"""Shared HTTP helper: one place for retries, timeouts and error handling.

Collectors receive an httpx.Client so tests can swap in httpx.MockTransport.
URLs are never logged, because API keys travel in the query string.
"""

import time
from typing import Any

import httpx

# Rate limits (429) and transient server errors are worth retrying.
# Other 4xx errors (bad key, not found) will not fix themselves, so we fail fast.
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


def make_client() -> httpx.Client:
    return httpx.Client(timeout=20.0)


def get_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
    *,
    retries: int = 3,
    backoff_s: float = 1.0,
) -> Any:
    """GET a URL and return its parsed JSON body.

    Retries rate limits and server errors with exponential backoff.
    Raises ApiError when the request still fails.
    """
    for attempt in range(retries + 1):
        response = client.get(url, params=params)
        is_last_attempt = attempt == retries
        if response.status_code not in RETRY_STATUSES or is_last_attempt:
            break
        time.sleep(backoff_s * 2**attempt)

    if response.status_code >= 400:
        # Only the response body is included; the request URL (with the key) is not.
        raise ApiError(response.status_code, response.text[:200])
    return response.json()
