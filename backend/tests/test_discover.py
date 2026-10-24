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
