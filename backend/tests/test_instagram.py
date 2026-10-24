from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.collectors.instagram import collect_hashtags, instagram_enabled
from app.collectors.instagram_parsers import media_format, parse_media
from app.models import Creator, Keyword, Post
from tests.instagram_fake import HASHTAG_ID, TOKEN, FakeInstagram, make_settings
from tests.youtube_fake import load

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def add_hashtag(session, term="lifeinsurance", *, platform="instagram", active=True):
    session.add(Keyword(term=term, platform=platform, active=active))
    session.commit()


def run_collect(session, fake, **settings):
    return collect_hashtags(session, fake.client(), make_settings(**settings), now=NOW)


# --- parser --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("media_type", "product_type", "expected"),
    [
        ("IMAGE", "FEED", "image"),
        ("CAROUSEL_ALBUM", "FEED", "carousel"),
        ("VIDEO", "FEED", "video"),
        ("VIDEO", "REELS", "reel"),
        ("SOMETHING_NEW", "FEED", None),
        (None, None, None),
    ],
)
def test_media_format(media_type, product_type, expected):
    assert media_format(media_type, product_type) == expected


def test_parse_media_maps_the_fields():
    post = parse_media(load("instagram_top_media_page1")["data"][1])
    assert post["external_id"] == "m2"
    assert post["url"] == "https://www.instagram.com/p/BBB222/"
    assert post["text"].startswith("The policy is never")
    assert (post["likes"], post["comments"]) == (2253, 25)
    assert post["format"] == "carousel"
    assert post["published_at"] == datetime(2026, 10, 9, 8, 30, tzinfo=UTC)
    # Not available for hashtag posts: unknown, never zero.
    assert (post["views"], post["shares"], post["title"], post["thumbnail_url"]) == (
        None,
        None,
        None,
        None,
    )


def test_parse_media_keeps_hidden_likes_unknown_and_empty_captions_none():
    item = {"id": "x", "permalink": "https://www.instagram.com/p/X/", "comments_count": 7}
    post = parse_media(item)
    assert post["likes"] is None
    assert post["comments"] == 7
    assert post["text"] is None
    assert post["published_at"] is None


def test_instagram_is_enabled_only_with_all_three_settings():
    assert instagram_enabled(make_settings()) is True
    assert instagram_enabled(make_settings(ig_access_token="")) is False
    assert instagram_enabled(make_settings(ig_user_id="")) is False
    assert instagram_enabled(make_settings(meta_graph_version="")) is False


# --- collector -----------------------------------------------------------------------------


def test_top_posts_are_stored_under_a_placeholder_creator(session):
    add_hashtag(session)
    fake = FakeInstagram()

    run = run_collect(session, fake)

    creator = session.scalars(select(Creator)).one()
    assert (creator.platform, creator.handle, creator.kind) == (
        "instagram",
        "#lifeinsurance",
        "hashtag",
    )
    assert creator.external_id == f"hashtag:{HASHTAG_ID}"
    assert creator.competitor_id is None

    posts = {p.external_id: p for p in session.scalars(select(Post))}
    assert set(posts) == {"m1", "m2", "m3", "m4"}  # m5 is from 2025: outside the 90 days
    assert posts["m1"].format == "image"
    assert posts["m2"].format == "carousel"
    assert posts["m1"].likes == 1800
    assert posts["m1"].text.startswith("If you could choose")
    assert posts["m1"].views is None
    assert all(p.platform == "instagram" for p in posts.values())
    assert all(p.location_status is None for p in posts.values())  # judged in a later step

    assert (run.kind, run.platform, run.status, run.items_ok) == ("collect", "instagram", "ok", 1)
    assert fake.calls_to("ig_hashtag_search") == 1
    assert fake.calls_to("top_media") == 2


def test_the_hash_sign_is_not_sent_to_the_api(session):
    add_hashtag(session, "#lifeinsurance")
    fake = FakeInstagram()
    run_collect(session, fake)
    assert fake.queries() == ["lifeinsurance"]


def test_paging_stops_at_the_page_limit(session):
    add_hashtag(session)
    fake = FakeInstagram()

    run_collect(session, fake, hashtag_max_pages=1)

    assert fake.calls_to("top_media") == 1
    assert {p.external_id for p in session.scalars(select(Post))} == {"m1", "m2", "m3"}


def test_collecting_twice_refreshes_metrics_without_duplicates(session):
    add_hashtag(session)
    fake = FakeInstagram()
    run_collect(session, fake)

    fake.page1["data"][0]["like_count"] = 9999
    run_collect(session, fake)

    posts = session.scalars(select(Post)).all()
    assert len(posts) == 4
    assert {p.external_id: p.likes for p in posts}["m1"] == 9999
    assert len(session.scalars(select(Creator)).all()) == 1


def test_pages_that_are_too_big_make_the_collector_step_down_and_stay_down(session):
    add_hashtag(session)
    fake = FakeInstagram()
    fake.max_page_size = 10

    run = run_collect(session, fake)

    # 15 is rejected once, then 10 is used for both pages without trying 15 again.
    assert fake.page_sizes() == [15, 10, 10]
    assert run.status == "ok"
    assert {p.external_id for p in session.scalars(select(Post))} == {"m1", "m2", "m3", "m4"}


def test_when_even_the_smallest_page_is_too_big_the_hashtag_fails(session):
    add_hashtag(session)
    fake = FakeInstagram()
    fake.max_page_size = 3

    run = run_collect(session, fake)

    assert fake.page_sizes() == [15, 10, 5]
    assert run.status == "error"
    assert session.scalars(select(Post)).all() == []


def test_an_error_on_a_later_page_keeps_the_earlier_pages(session):
    add_hashtag(session)
    fake = FakeInstagram()
    fake.fail_page2 = True

    run = run_collect(session, fake)

    assert {p.external_id for p in session.scalars(select(Post))} == {"m1", "m2", "m3"}
    assert run.status == "partial"
    assert "reduce the amount of data" in run.message


def test_an_error_on_the_first_page_is_a_failed_hashtag(session):
    add_hashtag(session)
    fake = FakeInstagram()
    fake.fail_page1 = True

    run = run_collect(session, fake)

    assert session.scalars(select(Post)).all() == []
    assert (run.status, run.items_ok, run.items_failed) == ("error", 0, 1)


def test_a_hashtag_that_does_not_exist_is_reported(session):
    add_hashtag(session, "nosuchtag")
    fake = FakeInstagram()
    fake.hashtag_missing = True

    run = run_collect(session, fake)

    assert run.status == "error"
    assert "hashtag #nosuchtag not found" in run.message
    assert fake.calls_to("top_media") == 0


def test_an_expired_token_stops_the_run_and_never_leaks_the_token(session):
    add_hashtag(session, "one")
    add_hashtag(session, "two")
    fake = FakeInstagram()
    fake.token_expired = True

    run = run_collect(session, fake)

    assert fake.calls_to("ig_hashtag_search") == 1  # no point trying the second hashtag
    assert run.status == "error"
    assert "token expired" in run.message
    assert TOKEN not in run.message


def test_only_active_instagram_keywords_are_used(session):
    add_hashtag(session, "lifeinsurance")
    add_hashtag(session, "paused", active=False)
    add_hashtag(session, "life insurance agent", platform=None)  # a YouTube search term
    add_hashtag(session, "youtube only", platform="youtube")
    fake = FakeInstagram()

    run_collect(session, fake)

    assert fake.queries() == ["lifeinsurance"]


def test_no_hashtags_means_nothing_to_do(session):
    fake = FakeInstagram()

    run = run_collect(session, fake)

    assert run.status == "ok"
    assert run.message == "no hashtags configured"
    assert fake.calls == []
