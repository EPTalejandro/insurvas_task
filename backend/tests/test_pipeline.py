from datetime import UTC, datetime

from sqlalchemy import select

from app.config import Settings
from app.models import Competitor, CompetitorScore, Keyword, Label, Post, PostScore
from app.pipeline import collect_step, enabled_platforms, refresh
from tests.instagram_fake import FakeInstagram
from tests.instagram_fake import make_settings as make_ig_settings
from tests.youtube_fake import FakeYouTube

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_refresh_with_discovery_runs_every_step_in_order(session):
    session.add(Keyword(term="life insurance agent", platform=None, active=True))
    session.commit()
    fake = FakeYouTube()

    runs = refresh(
        session, fake.client(), make_settings(youtube_api_key="k"), discover=True, now=NOW
    )

    assert [r.kind for r in runs] == ["discover", "collect", "label", "rank"]
    assert all(r.status == "ok" for r in runs)

    posts = {p.external_id: p for p in session.scalars(select(Post))}
    assert set(posts) == {"vid_short", "vid_long"}
    assert session.get(Label, posts["vid_long"].id).topic == "final_expense"
    assert session.get(Label, posts["vid_short"].id).topic == "term_life"

    # vid_short is 4 days old, vid_long 14: window 7 holds one, window 30 both.
    by_window = {}
    for score in session.scalars(select(PostScore)):
        by_window.setdefault(score.window_days, set()).add(score.post_id)
    assert by_window[7] == {posts["vid_short"].id}
    assert by_window[30] == {posts["vid_short"].id, posts["vid_long"].id}
    assert session.scalars(select(CompetitorScore)).all()


def test_refresh_without_discovery_uses_the_competitors_already_known(session):
    session.add(Keyword(term="x", platform=None, active=True))
    session.commit()
    settings = make_settings(youtube_api_key="k")
    fake = FakeYouTube()
    refresh(session, fake.client(), settings, discover=True, now=NOW)
    fake.calls.clear()

    runs = refresh(session, fake.client(), settings, now=NOW)

    assert [r.kind for r in runs] == ["collect", "label", "rank"]
    assert fake.calls_to("/search") == 0
    assert session.scalars(select(Competitor)).all()


def test_refresh_without_a_youtube_key_only_labels_and_ranks(session):
    fake = FakeYouTube()

    runs = refresh(session, fake.client(), make_settings(), discover=True, now=NOW)

    assert [r.kind for r in runs] == ["label", "rank"]
    assert fake.calls == []


# --- Instagram hashtags in the pipeline ----------------------------------------------------


def ig_settings(**overrides) -> Settings:
    return make_ig_settings(**overrides)


def add_hashtag(session, term="lifeinsurance"):
    session.add(Keyword(term=term, platform="instagram", active=True))
    session.commit()


def test_refresh_collects_hashtag_posts_judges_captions_and_ranks_the_us_ones(session):
    add_hashtag(session)
    fake = FakeInstagram()

    runs = refresh(
        session, FakeYouTube().client(), ig_settings(), now=NOW, instagram_client=fake.client()
    )

    assert [(r.kind, r.platform) for r in runs] == [
        ("collect", "instagram"),
        ("label", None),
        ("rank", None),
    ]
    posts = {p.external_id: p for p in session.scalars(select(Post))}
    assert {k: v.location_status for k, v in posts.items()} == {
        "m1": "probable_us",
        "m2": "likely_us",
        "m3": "non_us",
        "m4": "unverified",
    }
    assert all(p.label is not None for p in posts.values())

    by_window = {}
    for score in session.scalars(select(PostScore)):
        by_window.setdefault(score.window_days, set()).add(score.post_id)
    # Only the two US-looking posts are ranked (m1 is 19 days old, m2 15 days old).
    assert by_window[30] == {posts["m1"].id, posts["m2"].id}
    assert 7 not in by_window
    assert session.scalars(select(CompetitorScore)).all() == []


def test_refresh_runs_youtube_first_and_then_instagram(session):
    session.add(Keyword(term="life insurance agent", platform=None, active=True))
    add_hashtag(session)
    fake_yt, fake_ig = FakeYouTube(), FakeInstagram()
    settings = ig_settings(youtube_api_key="k")

    runs = refresh(
        session,
        fake_yt.client(),
        settings,
        discover=True,
        now=NOW,
        instagram_client=fake_ig.client(),
    )

    assert [(r.kind, r.platform) for r in runs] == [
        ("discover", "youtube"),
        ("collect", "youtube"),
        ("collect", "instagram"),
        ("label", None),
        ("rank", None),
    ]
    platforms = {p.platform for p in session.scalars(select(Post))}
    assert platforms == {"youtube", "instagram"}


def test_collect_step_can_be_limited_to_one_platform(session):
    add_hashtag(session)
    fake_yt, fake_ig = FakeYouTube(), FakeInstagram()
    settings = ig_settings(youtube_api_key="k")

    result = collect_step(
        session,
        fake_yt.client(),
        settings,
        NOW,
        platforms=["instagram"],
        instagram_client=fake_ig.client(),
    )

    assert [r.platform for r in result.runs] == ["instagram"]
    assert fake_yt.calls == []
    assert result.post_locations == {"probable_us": 1, "likely_us": 1, "non_us": 1, "unverified": 1}
    assert not result.creator_locations


def test_platforms_without_keys_are_not_collected(session):
    assert enabled_platforms(make_settings()) == []
    assert enabled_platforms(make_settings(youtube_api_key="k")) == ["youtube"]
    assert enabled_platforms(ig_settings()) == ["instagram"]
    assert enabled_platforms(ig_settings(youtube_api_key="k")) == ["youtube", "instagram"]
