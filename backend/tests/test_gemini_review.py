import json

import pytest

from app.discovery.gemini_review import (
    BATCH_SIZE,
    CreatorBrief,
    GeminiReviewer,
    build_prompt,
    quote_is_in,
)
from app.gemini_client import GeminiJson
from tests.gemini_fake import SECRET, Clock, FakeGemini


def reviewer(fake):
    clock = Clock()
    gemini = GeminiJson(fake, "m", 10, secret=SECRET, sleep=clock.sleep, clock=clock.clock)
    return GeminiReviewer(gemini)


def brief(creator_id=1, bio="Licensed in Texas. Call 512-555-0142", posts=("Why term life",)):
    return CreatorBrief(creator_id, "Jane Doe", bio, list(posts))


def verdict(creator_id=1, **overrides):
    base = {
        "creator_id": creator_id,
        "kind": "agent",
        "united_states": "yes",
        "evidence": "Licensed in Texas",
    }
    return base | overrides


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("Licensed in Texas", True),
        ("licensed   IN texas", True),  # case and spacing do not matter
        ("call 512-555-0142", True),
        ("Why term life", True),  # the recent posts count as text too
        ("Licensed in Ohio", False),
        ("", False),
        ("   ", False),
    ],
)
def test_quote_is_in(quote, expected):
    assert quote_is_in(quote, brief()) is expected


def test_the_prompt_lists_the_accounts_and_the_rules():
    prompt = build_prompt([brief(7), brief(8, bio="x" * 900)])

    assert '"creator_id": 7' in prompt
    assert "Licensed in Texas" in prompt
    assert "x" * 500 in prompt and "x" * 501 not in prompt  # long bios are cut
    assert "Do not guess" in prompt
    assert "carrier" in prompt


def test_a_supported_verdict_is_kept():
    fake = FakeGemini(lambda prompt: [verdict(1)])

    result = reviewer(fake).review([brief(1)])

    assert result[1].kind == "agent"
    assert result[1].united_states == "yes"
    assert result[1].evidence == "Licensed in Texas"


def test_an_answer_with_a_made_up_quote_becomes_unknown():
    fake = FakeGemini(lambda prompt: [verdict(1, evidence="Proudly serving Dallas, TX")])

    result = reviewer(fake).review([brief(1)])

    assert result[1].united_states == "unknown"
    assert result[1].evidence == "quote not found in the text"
    assert result[1].kind == "agent"  # the kind needs no quote


def test_an_answer_without_a_quote_cannot_say_yes():
    fake = FakeGemini(lambda prompt: [verdict(1, evidence="")])
    assert reviewer(fake).review([brief(1)])[1].united_states == "unknown"


def test_unknown_needs_no_evidence():
    fake = FakeGemini(lambda prompt: [verdict(1, united_states="unknown", evidence="")])
    result = reviewer(fake).review([brief(1)])
    assert result[1].united_states == "unknown"
    assert result[1].evidence == ""


def test_invalid_unknown_and_missing_answers_become_none():
    def answer(prompt):
        return [
            verdict(1),
            verdict(2, kind="influencer"),  # not one of the allowed kinds
            verdict(99),  # an account we did not ask about
        ]

    result = reviewer(FakeGemini(answer)).review([brief(1), brief(2), brief(3)])

    assert result[1] is not None
    assert result[2] is None
    assert result[3] is None
    assert 99 not in result


def test_a_failed_request_gives_none_for_everyone():
    fake = FakeGemini(lambda prompt: RuntimeError("quota"))
    assert reviewer(fake).review([brief(1), brief(2)]) == {1: None, 2: None}


def test_accounts_are_sent_in_batches_of_ten():
    fake = FakeGemini(lambda prompt: [])
    briefs = [brief(i) for i in range(1, 26)]

    reviewer(fake).review(briefs)

    assert BATCH_SIZE == 10
    assert len(fake.calls) == 3
    sent = [len(call.prompt.strip().splitlines()) for call in fake.calls]
    assert all(line_count > 10 for line_count in sent)  # instructions plus up to ten accounts
    last = [
        json.loads(line)["creator_id"]
        for line in fake.calls[2].prompt.splitlines()
        if line.startswith("{")
    ]
    assert last == [21, 22, 23, 24, 25]
