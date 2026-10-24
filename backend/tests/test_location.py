from sqlalchemy import select

from app.discovery.location import (
    LIKELY_US,
    NON_US,
    UNVERIFIED,
    US,
    assess_location,
    update_locations,
)
from app.models import Competitor, Creator, Post


def test_us_country_wins():
    result = assess_location("US", "bio", [])
    assert (result.status, result.evidence) == (US, "channel country: US")


def test_other_country_is_non_us_even_with_us_looking_text():
    result = assess_location("IN", "Licensed in TX. Call 512-555-0142", [])
    assert (result.status, result.evidence) == (NON_US, "channel country: IN")


def test_license_words_in_bio_make_it_likely_us():
    result = assess_location(None, "Licensed in TX and FL. NPN 1234567", [])
    assert result.status == LIKELY_US
    assert "NPN" in result.evidence or "Licensed in" in result.evidence


def test_licensed_insurance_agents_is_not_a_license_mention():
    # "licensed in" must not match the start of "licensed insurance".
    result = assess_location(None, "We sell leads to licensed insurance agents", [])
    assert result.status == UNVERIFIED


def test_us_phone_number_in_a_post_makes_it_likely_us():
    result = assess_location(None, None, ["Free quote", "Call or text 512-555-0142 today"])
    assert result.status == LIKELY_US
    assert "512-555-0142" in result.evidence


def test_indian_market_text_makes_it_non_us():
    texts = ["Best LIC plan", "Returns up to ₹5 lakh", "Hindi: बीमा क्या है"]
    result = assess_location(None, None, texts)
    assert result.status == NON_US
    assert "Indian-market" in result.evidence


def test_a_single_indian_mention_is_not_enough():
    result = assess_location(None, "I visited India last year", [])
    assert result.status == UNVERIFIED


def test_weak_us_signals_stay_unverified_but_leave_a_note():
    texts = ["Texas, Florida and Ohio rates", "Medicare and IRS rules"]
    result = assess_location(None, None, texts)
    assert result.status == UNVERIFIED
    assert result.evidence.startswith("weak US signals")


def test_no_signals_is_unverified_without_evidence():
    result = assess_location(None, "Helping families", ["Why term life matters"])
    assert (result.status, result.evidence) == (UNVERIFIED, None)


def add_creator(session, channel_id, *, country=None, bio=None, posts=(), status="active"):
    competitor = Competitor(name=channel_id, kind="agent", status=status)
    creator = Creator(
        competitor=competitor,
        platform="youtube",
        external_id=channel_id,
        handle=channel_id,
        name=channel_id,
        bio=bio,
        country=country,
        location_status="us" if country == "US" else "unverified",
    )
    session.add(creator)
    session.flush()
    for index, title in enumerate(posts):
        session.add(
            Post(
                creator_id=creator.id,
                platform="youtube",
                external_id=f"{channel_id}-{index}",
                url="https://example.com",
                title=title,
            )
        )
    session.commit()
    return creator


def test_update_locations_uses_posts_and_excludes_non_us(session):
    indian = add_creator(session, "UCindian", posts=["LIC plan", "₹5 lakh cover", "IRDAI rules"])
    licensed = add_creator(session, "UClicensed", posts=["I am licensed in Texas"])
    silent = add_creator(session, "UCsilent", posts=["Why term life matters"])
    american = add_creator(session, "UCamerican", country="US")

    counts = update_locations(session)

    assert indian.location_status == NON_US
    assert indian.is_relevant is False
    assert session.get(Competitor, indian.competitor_id).status == "excluded"

    assert licensed.location_status == LIKELY_US
    assert "licensed in" in licensed.location_evidence.lower()
    assert session.get(Competitor, licensed.competitor_id).status == "active"

    assert silent.location_status == UNVERIFIED
    assert session.get(Competitor, silent.competitor_id).status == "active"

    assert american.location_status == US  # has a country, left untouched
    # Counts only include accounts that are still relevant.
    assert counts == {LIKELY_US: 1, UNVERIFIED: 1, US: 1}


def test_update_locations_is_repeatable(session):
    add_creator(session, "UClicensed", posts=["licensed in Ohio"])
    first = update_locations(session)
    second = update_locations(session)
    assert first == second
    assert len(session.scalars(select(Creator)).all()) == 1
