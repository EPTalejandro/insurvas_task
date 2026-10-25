"""A fake Gemini client for tests, shaped like `genai.Client` (`client.models.generate_content`)."""

import json
import re
from types import SimpleNamespace

SECRET = "SECRET-GEMINI-KEY"
RESOLVED_MODEL = "gemini-3.5-flash-lite"


def label_for(post_id, **overrides) -> dict:
    label = {
        "post_id": post_id,
        "topic": "iul",
        "hook_type": "question",
        "hook_text": "Gemini's own words",
        "cta": "book_call",
        "is_relevant": True,
        "confidence": 0.9,
    }
    return label | overrides


def ids_in(prompt: str) -> list[int]:
    return [int(n) for n in re.findall(r'"post_id": (\d+)', prompt)]


class FakeGemini:
    """`answer` gets the prompt and returns a list (sent as JSON), a string (sent as is) or an
    exception (raised). By default every post in the prompt gets a valid IUL label."""

    def __init__(self, answer=None) -> None:
        self.answer = answer or (lambda prompt: [label_for(i) for i in ids_in(prompt)])
        self.calls: list[SimpleNamespace] = []
        self.models = self  # so that client.models.generate_content works

    def generate_content(self, *, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, prompt=contents, config=config))
        out = self.answer(contents)
        if isinstance(out, Exception):
            raise out
        text = out if isinstance(out, str) else json.dumps(out)
        return SimpleNamespace(text=text, model_version=RESOLVED_MODEL)


class Clock:
    """A clock and a sleep that never really wait."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
