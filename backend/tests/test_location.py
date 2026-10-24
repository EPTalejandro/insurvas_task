import pytest
from sqlalchemy import select

from app.discovery.location import (
    LIKELY_US,
    NON_US,
    PROBABLE_US,
    UNVERIFIED,
    US,
    assess_caption,
    assess_location,
    update_locations,
    update_post_locations,
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


# --- captions of hashtag posts (no author is known) ---------------------------------------


@pytest.mark.parametrize(
    ("caption", "status", "evidence_part"),
    [
        (
            "The policy is never the interesting part. Call (615) 905-6050",
            LIKELY_US,
            "(615) 905-6050",
        ),
        (
            "I am licensed in Texas and Ohio. Ask me about your family plan.",
            LIKELY_US,
            "licensed in",
        ),
        ("Hola! Llama al 512-555-0142 para tu seguro de vida", LIKELY_US, "512-555-0142"),
        ("What would you leave your children? Ask about IUL in Texas", PROBABLE_US, "iul"),
        ("Final expense plans start at $29 a month for your family", PROBABLE_US, "$29"),
        (
            "Join my free training for agents on 10/20 at 6:00pm EST, you will love it",
            PROBABLE_US,
            "EST",
        ),
        (
            "Life insurance is easiest to get when you're young. Don't wait for the family.",
            UNVERIFIED,
            "no US cue",
        ),
        (
            "Crowdfunding is NOT life insurance. #GetLifeInsurance . . . #lifeinsurance",
            UNVERIFIED,
            "no US cue",
        ),
        ("#lifeinsurance #insurance", UNVERIFIED, "no text"),
        ("", UNVERIFIED, "no text"),
        (None, UNVERIFIED, "no text"),
        ("Returns up to ₹5 on your plan, get the policy for your family", NON_US, "₹"),
        ("Best life insurance in Nigeria for the whole family", NON_US, "Nigeria"),
        ("NAMA MANTAN JADI MASALAH Jadi kalau kamu punya polis sekarang", NON_US, "not in English"),
        ("ઘણા લોકો પૈસા કમાય છે… પણ legal planning નથી કરતા", NON_US, "not in English"),
    ],
)
def test_assess_caption(caption, status, evidence_part):
    result = assess_caption(caption)
    assert result.status == status
    assert evidence_part in result.evidence


def test_hashtags_in_a_caption_do_not_count_as_english_words():
    # Only hashtags are English here; the sentence itself is Indonesian.
    caption = "Jadi kalau kamu punya polis coba dibuka lagi #life #insurance #family #policy"
    assert assess_caption(caption).status == NON_US


def test_a_non_us_marker_beats_a_us_cue():
    result = assess_caption("Life insurance for your family in India and Texas")
    assert result.status == NON_US


def test_captions_never_reach_the_us_status():
    assert assess_caption("Call 512-555-0142, licensed in Texas").status == LIKELY_US


def add_post(session, creator, external_id, caption):
    post = Post(
        creator_id=creator.id,
        platform=creator.platform,
        external_id=external_id,
        url="https://example.com",
        text=caption,
    )
    session.add(post)
    return post


def test_update_post_locations_judges_hashtag_posts_only(session):
    hashtag = Creator(
        platform="instagram", external_id="hashtag:1", handle="#x", name="x", kind="hashtag"
    )
    channel = Creator(platform="youtube", external_id="UC1", handle="@a", name="a", kind="agent")
    session.add_all([hashtag, channel])
    session.flush()
    us = add_post(session, hashtag, "h1", "Call 512-555-0142 for a quote on your family plan")
    other = add_post(session, hashtag, "h2", "NAMA MANTAN JADI MASALAH Jadi kalau kamu punya polis")
    video = add_post(session, channel, "v1", "Call 512-555-0142")
    session.commit()

    counts = update_post_locations(session)

    assert counts == {LIKELY_US: 1, NON_US: 1}
    assert (us.location_status, other.location_status) == (LIKELY_US, NON_US)
    assert "512-555-0142" in us.location_evidence
    assert video.location_status is None  # competitor posts are not judged by caption


def test_update_post_locations_is_repeatable(session):
    hashtag = Creator(
        platform="instagram", external_id="hashtag:1", handle="#x", name="x", kind="hashtag"
    )
    session.add(hashtag)
    session.flush()
    post = add_post(session, hashtag, "h1", "Ask about IUL for your family in Texas")
    session.commit()
    update_post_locations(session)

    post.text = "Call 512-555-0142 for a quote on your family plan"
    session.commit()
    update_post_locations(session)

    assert post.location_status == LIKELY_US
