from datetime import datetime

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


# --- Instagram accounts linked to a competitor ---------------------------------------------


def add_account(session, competitor, platform, handle, *, bio=None, posts=(), country=None):
    creator = Creator(
        competitor=competitor,
        platform=platform,
        external_id=handle,
        handle=handle,
        name=handle,
        bio=bio,
        country=country,
        kind="agent",
        location_status="us" if country == "US" else "unverified",
        location_evidence="channel country: US" if country == "US" else None,
    )
    session.add(creator)
    session.flush()
    for index, title in enumerate(posts):
        session.add(
            Post(
                creator_id=creator.id,
                platform=platform,
                external_id=f"{handle}-{index}",
                url="https://example.com",
                title=title,
            )
        )
    session.commit()
    return creator


def test_an_instagram_account_inherits_a_verified_youtube_channel(session):
    competitor = Competitor(name="jane", kind="agent", status="active")
    session.add(competitor)
    youtube = add_account(session, competitor, "youtube", "@jane", country="US")
    instagram = add_account(
        session, competitor, "instagram", "jane_ig", posts=["Why term life matters"]
    )

    update_locations(session)

    assert instagram.location_status == LIKELY_US
    assert "same competitor as youtube @jane" in instagram.location_evidence
    assert "channel country: US" in instagram.location_evidence
    assert youtube.location_status == US


def test_a_youtube_channel_judged_in_the_same_run_can_be_inherited(session):
    competitor = Competitor(name="jane", kind="agent", status="active")
    session.add(competitor)
    youtube = add_account(session, competitor, "youtube", "@jane", posts=["Call 512-555-0142"])
    instagram = add_account(session, competitor, "instagram", "jane_ig")

    update_locations(session)

    assert youtube.location_status == LIKELY_US
    assert instagram.location_status == LIKELY_US


def test_an_instagram_account_with_its_own_evidence_keeps_it(session):
    competitor = Competitor(name="jane", kind="agent", status="active")
    session.add(competitor)
    add_account(session, competitor, "youtube", "@jane", country="US")
    instagram = add_account(session, competitor, "instagram", "jane_ig", bio="Licensed in Ohio")

    update_locations(session)

    assert instagram.location_status == LIKELY_US
    assert "license mention" in instagram.location_evidence


def test_nothing_is_inherited_from_an_unverified_account(session):
    competitor = Competitor(name="jane", kind="agent", status="active")
    session.add(competitor)
    add_account(session, competitor, "youtube", "@jane", posts=["Good morning"])
    instagram = add_account(session, competitor, "instagram", "jane_ig")

    update_locations(session)

    assert instagram.location_status == UNVERIFIED
    assert instagram.location_evidence is None


def test_a_non_us_instagram_account_is_switched_off_but_the_competitor_stays(session):
    competitor = Competitor(name="jane", kind="agent", status="active")
    session.add(competitor)
    youtube = add_account(session, competitor, "youtube", "@jane", country="US")
    instagram = add_account(
        session,
        competitor,
        "instagram",
        "jane_ig",
        posts=["LIC plan", "₹5 lakh cover", "IRDAI rules"],
    )

    counts = update_locations(session)

    assert instagram.location_status == NON_US
    assert instagram.is_relevant is False
    assert youtube.is_relevant is True
    assert competitor.status == "active"
    assert counts == {US: 1}


def test_a_competitor_with_no_account_left_is_excluded(session):
    competitor = Competitor(name="jane", kind="agent", status="active")
    session.add(competitor)
    add_account(session, competitor, "instagram", "jane_ig", posts=["LIC plan", "₹5 lakh", "IRDAI"])

    update_locations(session)

    assert competitor.status == "excluded"


def test_hashtag_placeholders_are_not_judged_as_accounts(session):
    tag = Creator(
        platform="instagram", external_id="hashtag:1", handle="#x", name="x", kind="hashtag"
    )
    session.add(tag)
    session.commit()

    assert update_locations(session) == {}
    assert tag.location_status == "unverified"


# --- Gemini for the accounts without evidence ----------------------------------------------


def gemini_reviewer(answer):
    from app.discovery.gemini_review import GeminiReviewer
    from app.gemini_client import GeminiJson
    from tests.gemini_fake import Clock, FakeGemini

    fake = FakeGemini(answer)
    clock = Clock()
    return GeminiReviewer(GeminiJson(fake, "m", 10, sleep=clock.sleep, clock=clock.clock)), fake


def verdicts(by_handle):
    """An answer function: {handle: (united_states, evidence)}."""
    import json

    def answer(prompt):
        accounts = [json.loads(line) for line in prompt.splitlines() if line.startswith("{")]
        out = []
        for account in accounts:
            states, evidence = by_handle.get(account["name"], ("unknown", ""))
            out.append(
                {
                    "creator_id": account["creator_id"],
                    "kind": "agent",
                    "united_states": states,
                    "evidence": evidence,
                }
            )
        return out

    return answer


def solo(session, handle, bio=None, posts=()):
    competitor = Competitor(name=handle, kind="agent", status="active")
    session.add(competitor)
    return competitor, add_account(session, competitor, "youtube", handle, bio=bio, posts=posts)


def test_gemini_settles_an_account_the_rules_could_not(session):
    competitor, creator = solo(session, "jane", bio="Helping Dallas families protect what matters")
    reviewer, _ = gemini_reviewer(verdicts({"jane": ("yes", "Helping Dallas families")}))

    update_locations(session, reviewer)

    assert creator.location_status == PROBABLE_US  # a judgment, not hard proof
    assert creator.location_evidence == "Gemini quoted: 'Helping Dallas families'"
    assert competitor.status == "active"


def test_gemini_saying_no_switches_the_account_off(session):
    competitor, creator = solo(session, "ravi", bio="Mumbai based advisor for policy holders")
    reviewer, _ = gemini_reviewer(verdicts({"ravi": ("no", "Mumbai based advisor")}))

    update_locations(session, reviewer)

    assert creator.location_status == NON_US
    assert creator.is_relevant is False
    assert competitor.status == "excluded"


def test_a_quote_that_is_not_in_the_text_changes_nothing(session):
    _, creator = solo(session, "jane", bio="Life insurance for families")
    reviewer, _ = gemini_reviewer(verdicts({"jane": ("yes", "Serving Austin, Texas")}))

    update_locations(session, reviewer)

    assert creator.location_status == UNVERIFIED


def test_gemini_only_sees_accounts_the_rules_left_unverified(session):
    solo(session, "licensed", bio="Licensed in Ohio")  # the rules settle this one
    solo(session, "quiet", bio="Helping families")
    reviewer, fake = gemini_reviewer(verdicts({}))

    update_locations(session, reviewer)

    assert len(fake.calls) == 1
    assert '"name": "quiet"' in fake.calls[0].prompt
    assert '"name": "licensed"' not in fake.calls[0].prompt


def test_gemini_reads_the_bio_and_the_three_latest_posts(session):
    _, creator = solo(
        session,
        "jane",
        bio="Helping families",
        posts=["post one", "post two", "post three", "post four"],
    )
    for index, post in enumerate(
        session.scalars(select(Post).where(Post.creator_id == creator.id))
    ):
        post.published_at = datetime(2026, 10, 1 + index)
    session.commit()
    reviewer, fake = gemini_reviewer(verdicts({}))

    update_locations(session, reviewer)

    prompt = fake.calls[0].prompt
    assert "Helping families" in prompt
    assert "post four" in prompt and "post two" in prompt
    assert "post one" not in prompt  # only the three most recent


def test_without_a_gemini_answer_the_account_can_still_inherit(session):
    competitor = Competitor(name="jane", kind="agent", status="active")
    session.add(competitor)
    add_account(session, competitor, "youtube", "@jane", country="US")
    instagram = add_account(session, competitor, "instagram", "jane_ig", bio="Helping families")
    broken, _ = gemini_reviewer(lambda prompt: RuntimeError("quota"))

    update_locations(session, broken)

    assert instagram.location_status == LIKELY_US
    assert "same competitor" in instagram.location_evidence
