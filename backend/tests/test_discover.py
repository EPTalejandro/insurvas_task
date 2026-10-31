import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import Settings
from app.discovery.discover import discover_youtube
from app.models import Competitor, Creator, Keyword, Run
from tests.youtube_fake import FORBIDDEN_BODY, QUOTA_BODY, FakeYouTube

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def make_settings(**overrides) -> Settings:
    values = {
        "youtube_api_key": "test-key",
        "youtube_discovery_quota": 3000,
        "max_competitors": 100,
    }
    return Settings(_env_file=None, **{**values, **overrides})


def add_keywords(session, *terms: str) -> None:
    session.add_all(Keyword(term=term, platform=None, active=True) for term in terms)
    session.commit()


def run_discover(session, fake: FakeYouTube, **settings):
    return discover_youtube(session, fake.client(), make_settings(**settings), now=NOW)


def test_discover_keeps_agents_and_agencies_and_drops_the_rest(session):
    add_keywords(session, "life insurance agent", "final expense agent")
    fake = FakeYouTube()

    run = run_discover(session, fake)

    creators = {c.name: c for c in session.scalars(select(Creator))}
    assert len(creators) == 5
    assert creators["Jane Doe - Final Expense Agent"].is_relevant is True
    assert creators["Jane Doe - Final Expense Agent"].kind == "agent"
    assert creators["Sunrise Insurance Agency"].kind == "agency"
    assert creators["State Farm"].is_relevant is False
    assert creators["Pixel Quest"].is_relevant is False
    assert creators["Pixel Quest"].followers is None
    # The channel says it is in India, so it never becomes a competitor.
    mumbai = creators["Mumbai Life Insurance Agency"]
    assert (mumbai.is_relevant, mumbai.location_status, mumbai.competitor_id) == (
        False,
        "non_us",
        None,
    )
    assert mumbai.location_evidence == "channel country: IN"
    jane = creators["Jane Doe - Final Expense Agent"]
    assert (jane.country, jane.location_status) == ("US", "us")
    assert creators["Sunrise Insurance Agency"].location_status == "unverified"
    assert creators["Jane Doe - Final Expense Agent"].discovered_via == "life insurance agent"

    competitors = session.scalars(select(Competitor)).all()
    assert sorted(c.name for c in competitors) == [
        "Jane Doe - Final Expense Agent",
        "Sunrise Insurance Agency",
    ]
    assert all(c.status == "active" for c in competitors)
    assert all(c.discovery_score > 0 for c in competitors)
    assert creators["State Farm"].competitor_id is None

    assert run.status == "ok"
    # 2 searches (the fake has no next page) + 1 channels request
    assert run.quota_used == 201
    assert run.items_ok == 5


def test_without_search_terms_nothing_is_searched(session):
    # A fresh database has no terms: they are all added in the Sources tab.
    fake = FakeYouTube()
    session.add(Keyword(term="off", platform=None, active=False))
    session.commit()

    run = run_discover(session, fake)

    assert (run.status, run.quota_used) == ("ok", 0)
    assert run.message == "no search terms: add some in the Sources tab"
    assert fake.calls == []


def test_discover_twice_does_not_duplicate(session):
    add_keywords(session, "life insurance agent")
    fake = FakeYouTube()
    run_discover(session, fake)
    run_discover(session, fake)

    assert len(session.scalars(select(Creator)).all()) == 5
    assert len(session.scalars(select(Competitor)).all()) == 2
    assert len(session.scalars(select(Run)).all()) == 2


def test_only_the_best_candidates_become_active_when_slots_are_limited(session):
    add_keywords(session, "life insurance agent")
    run_discover(session, FakeYouTube(), max_competitors=1)

    status = {c.name: c.status for c in session.scalars(select(Competitor))}
    assert status == {
        "Jane Doe - Final Expense Agent": "active",  # 5,200 subscribers
        "Sunrise Insurance Agency": "candidate",  # 800 subscribers
    }


def test_existing_active_competitors_are_kept(session):
    add_keywords(session, "life insurance agent")
    run_discover(session, FakeYouTube(), max_competitors=1)
    # The bigger channel is already active; a later run must not swap it out.
    run_discover(session, FakeYouTube(), max_competitors=1)

    status = {c.name: c.status for c in session.scalars(select(Competitor))}
    assert status["Jane Doe - Final Expense Agent"] == "active"
    assert status["Sunrise Insurance Agency"] == "candidate"


def test_quota_budget_limits_the_number_of_searches(session):
    add_keywords(session, "one", "two", "three")
    fake = FakeYouTube()

    run = run_discover(session, fake, youtube_discovery_quota=200)

    assert fake.calls_to("/search") == 2
    assert run.quota_used == 201


def test_a_failing_keyword_gives_a_partial_run(session):
    add_keywords(session, "good term", "bad term")
    fake = FakeYouTube()
    fake.search_errors["bad term"] = (403, FORBIDDEN_BODY)

    run = run_discover(session, fake)

    assert run.status == "partial"
    assert run.items_failed == 1
    assert len(session.scalars(select(Creator)).all()) == 5


def test_quota_exceeded_stops_all_searches(session):
    add_keywords(session, "first", "second", "third")
    fake = FakeYouTube()
    for term in ("first", "second", "third"):
        fake.search_errors[term] = (403, QUOTA_BODY)

    run = run_discover(session, fake)

    assert fake.calls_to("/search") == 1
    assert run.status == "error"
    assert "quotaExceeded" in run.message


# --- Gemini as a second opinion on accounts the rules were unsure about ------------------------


def unsure_channels(fake: FakeYouTube) -> None:
    """Two channels the rules cannot settle: one with no insurance word, one with only a guess."""
    fake.search["items"] += [
        {
            "id": {"videoId": "v-legacy"},
            "snippet": {"channelId": "UClegacy", "channelTitle": "Peter"},
        },
        {"id": {"videoId": "v-tom"}, "snippet": {"channelId": "UCtom", "channelTitle": "Tom Lee"}},
    ]
    fake.channels["items"] += [
        {
            "id": "UClegacy",
            "snippet": {
                "title": "Peter Roberts",
                "description": "Founder, Legacy Family Life. I'm hiring agents",
            },
            "statistics": {"subscriberCount": "64100"},
        },
        {
            "id": "UCtom",
            "snippet": {"title": "Tom Lee", "description": "Final expense and IUL explained"},
            "statistics": {"subscriberCount": "9000"},
        },
    ]


def reviewer_saying(**by_name):
    """A reviewer whose Gemini answers `by_name` = {account name: kind}."""
    from app.discovery.gemini_review import GeminiReviewer
    from app.gemini_client import GeminiJson
    from tests.gemini_fake import Clock, FakeGemini

    def answer(prompt):
        found = [json.loads(line) for line in prompt.splitlines() if line.startswith("{")]
        return [
            {
                "creator_id": a["creator_id"],
                "kind": by_name[a["name"]],
                "united_states": "unknown",
                "evidence": "",
            }
            for a in found
            if a["name"] in by_name
        ]

    fake = FakeGemini(answer)
    clock = Clock()
    return GeminiReviewer(GeminiJson(fake, "m", 10, sleep=clock.sleep, clock=clock.clock)), fake


def test_without_a_reviewer_the_rules_decide(session):
    add_keywords(session, "life insurance agent")
    fake = FakeYouTube()
    unsure_channels(fake)

    run_discover(session, fake)

    creators = {c.name: c for c in session.scalars(select(Creator))}
    assert creators["Peter Roberts"].is_relevant is False  # no insurance word in name or bio
    assert creators["Tom Lee"].is_relevant is True
    assert creators["Tom Lee"].kind == "agent"  # the rules' default guess


def test_gemini_can_rescue_and_reject_accounts_the_rules_were_unsure_about(session):
    add_keywords(session, "life insurance agent")
    fake = FakeYouTube()
    unsure_channels(fake)
    reviewer, gemini = reviewer_saying(**{"Peter Roberts": "agency", "Tom Lee": "other"})

    discover_youtube(session, fake.client(), make_settings(), now=NOW, reviewer=reviewer)

    creators = {c.name: c for c in session.scalars(select(Creator))}
    assert (creators["Peter Roberts"].is_relevant, creators["Peter Roberts"].kind) == (
        True,
        "agency",
    )
    assert (creators["Tom Lee"].is_relevant, creators["Tom Lee"].kind) == (False, None)
    names = {c.name for c in session.scalars(select(Competitor))}
    assert "Peter Roberts" in names  # a rescued account becomes a competitor
    assert "Tom Lee" not in names


def test_only_unsure_accounts_are_sent_to_gemini(session):
    add_keywords(session, "life insurance agent")
    fake = FakeYouTube()
    unsure_channels(fake)
    reviewer, gemini = reviewer_saying()

    discover_youtube(session, fake.client(), make_settings(), now=NOW, reviewer=reviewer)

    sent = [
        json.loads(line)["name"]
        for call in gemini.calls
        for line in call.prompt.splitlines()
        if line.startswith("{")
    ]
    assert sorted(sent) == ["Peter Roberts", "Tom Lee"]  # not the clear agent, agency or carrier


def test_when_gemini_gives_no_answer_the_rules_guess_stays(session):
    from app.discovery.gemini_review import GeminiReviewer
    from app.gemini_client import GeminiJson
    from tests.gemini_fake import FakeGemini

    add_keywords(session, "life insurance agent")
    fake = FakeYouTube()
    unsure_channels(fake)
    broken = GeminiReviewer(GeminiJson(FakeGemini(lambda p: RuntimeError("quota")), "m", 10))

    discover_youtube(session, fake.client(), make_settings(), now=NOW, reviewer=broken)

    creators = {c.name: c for c in session.scalars(select(Creator))}
    assert creators["Peter Roberts"].is_relevant is False
    assert creators["Tom Lee"].is_relevant is True


def test_gemini_cannot_bring_back_a_non_us_channel(session):
    add_keywords(session, "life insurance agent")
    fake = FakeYouTube()
    fake.channels["items"][4]["snippet"]["description"] = "Life insurance agency. Hiring agents"
    fake.channels["items"][4]["snippet"]["title"] = "Mumbai Team"
    reviewer, _ = reviewer_saying(**{"Mumbai Team": "agency"})

    discover_youtube(session, fake.client(), make_settings(), now=NOW, reviewer=reviewer)

    mumbai = session.scalars(select(Creator).where(Creator.name == "Mumbai Team")).one()
    assert (mumbai.country, mumbai.is_relevant) == ("IN", False)
