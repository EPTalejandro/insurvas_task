"""A small wrapper around the Gemini API: a prompt goes in, a list of JSON objects comes out.

Shared by the post labeler and the account reviewer. It keeps to the free-tier request rate,
never lets the API key reach a message, and stops calling after repeated failures, so a bad
day (quota used up, no network) costs a few seconds instead of hundreds of slow failed requests.
"""

import json
import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import types

from app.config import Settings

MAX_CONSECUTIVE_FAILURES = 3


class GeminiJson:
    def __init__(
        self,
        client: Any,
        model: str,
        rpm: int,
        *,
        secret: str = "",
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self.model = model
        self._interval = 60 / max(rpm, 1)  # seconds between two requests
        self._secret = secret
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None
        self._failures = 0
        self.model_used: str | None = None  # the model that really answered
        self.last_error: str | None = None
        self.requests = 0

    @property
    def available(self) -> bool:
        return self._failures < MAX_CONSECUTIVE_FAILURES

    def _wait_turn(self) -> None:
        if self._last_call is not None:
            wait = self._interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _scrub(self, text: str) -> str:
        return text.replace(self._secret, "***") if self._secret else text

    def ask(self, prompt: str, schema: Any) -> list[dict[str, Any]] | None:
        """Send a prompt, get a list of objects shaped like `schema`. None when anything fails."""
        if not self.available:
            return None
        self._wait_turn()
        self.requests += 1
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0,  # the same post should get the same label every time
                ),
            )
            data = json.loads(response.text)
            if not isinstance(data, list):
                raise ValueError("the answer is not a JSON list")
        except Exception as error:  # network, quota, blocked or malformed answers all end here
            self._failures += 1
            self.last_error = self._scrub(f"{type(error).__name__}: {error}")[:200]
            return None
        self._failures = 0
        self.model_used = getattr(response, "model_version", None) or self.model
        return data


def make_gemini(settings: Settings) -> GeminiJson | None:
    """The Gemini connection, or None when there is no key or the rules labeler is forced."""
    if not settings.gemini_api_key or settings.labeler == "rules":
        return None
    client = genai.Client(api_key=settings.gemini_api_key)
    return GeminiJson(
        client, settings.gemini_model, settings.gemini_rpm, secret=settings.gemini_api_key
    )
