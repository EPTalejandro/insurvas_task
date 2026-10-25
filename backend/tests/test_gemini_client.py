import pytest
from pydantic import BaseModel

from app.config import Settings
from app.gemini_client import MAX_CONSECUTIVE_FAILURES, GeminiJson, make_gemini
from tests.gemini_fake import RESOLVED_MODEL, SECRET, Clock, FakeGemini


class Item(BaseModel):
    post_id: int


def make(fake, *, rpm=10, clock=None):
    clock = clock or Clock()
    return GeminiJson(
        fake, "gemini-flash-lite-latest", rpm, secret=SECRET, sleep=clock.sleep, clock=clock.clock
    )


def test_a_json_list_comes_back_and_the_real_model_is_remembered():
    fake = FakeGemini(lambda prompt: [{"post_id": 1}])
    gemini = make(fake)

    assert gemini.ask("hello", list[Item]) == [{"post_id": 1}]
    assert gemini.model_used == RESOLVED_MODEL  # the alias resolved to a real model
    assert gemini.last_error is None


def test_the_request_asks_for_json_with_the_schema_and_no_randomness():
    fake = FakeGemini(lambda prompt: [])
    make(fake).ask("hello", list[Item])

    call = fake.calls[0]
    assert call.model == "gemini-flash-lite-latest"
    assert call.prompt == "hello"
    assert call.config.response_mime_type == "application/json"
    assert call.config.response_schema == list[Item]
    assert call.config.temperature == 0


def test_requests_are_spaced_to_the_requests_per_minute_limit():
    clock = Clock()
    gemini = make(FakeGemini(lambda prompt: []), rpm=10, clock=clock)

    gemini.ask("one", list[Item])
    gemini.ask("two", list[Item])
    clock.now += 2  # some time passes by itself
    gemini.ask("three", list[Item])

    assert clock.slept[0] == pytest.approx(6.0)  # 10 per minute is one every 6 seconds
    assert clock.slept[1] == pytest.approx(4.0)  # only the missing part is waited


@pytest.mark.parametrize(
    "answer",
    [RuntimeError("quota exhausted"), "this is not json", '{"not": "a list"}'],
)
def test_any_failure_gives_none_and_a_message(answer):
    gemini = make(FakeGemini(lambda prompt: answer))

    assert gemini.ask("hello", list[Item]) is None
    assert gemini.last_error


def test_the_api_key_never_reaches_an_error_message():
    leaky = RuntimeError(f"request failed for key={SECRET}")
    gemini = make(FakeGemini(lambda prompt: leaky))

    gemini.ask("hello", list[Item])

    assert SECRET not in gemini.last_error
    assert "***" in gemini.last_error


def test_after_repeated_failures_gemini_is_not_called_again():
    fake = FakeGemini(lambda prompt: RuntimeError("quota exhausted"))
    gemini = make(fake)

    for _ in range(MAX_CONSECUTIVE_FAILURES + 4):
        gemini.ask("hello", list[Item])

    assert len(fake.calls) == MAX_CONSECUTIVE_FAILURES
    assert gemini.available is False


def test_a_success_resets_the_failure_count():
    answers = iter([RuntimeError("a"), RuntimeError("b"), [], RuntimeError("c"), RuntimeError("d")])
    fake = FakeGemini(lambda prompt: next(answers))
    gemini = make(fake)

    for _ in range(5):
        gemini.ask("hello", list[Item])

    assert gemini.available is True
    assert len(fake.calls) == 5


def test_no_key_or_forced_rules_means_no_gemini():
    assert make_gemini(Settings(_env_file=None)) is None
    assert make_gemini(Settings(_env_file=None, gemini_api_key="k", labeler="rules")) is None


def test_a_key_builds_a_connection_without_calling_the_network():
    gemini = make_gemini(
        Settings(_env_file=None, gemini_api_key="k", gemini_model="m", gemini_rpm=5)
    )
    assert gemini.model == "m"
    assert gemini.available
