from datetime import UTC, datetime

from sqlalchemy import select

from app.config import Settings
from app.models import Competitor, CompetitorScore, Creator, Keyword, Label, Post, PostScore
from app.pipeline import collect_step, enabled_platforms, refresh
from tests.instagram_fake import FakeInstagram, media
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
        ("link", "instagram"),
        ("collect", "instagram"),  # linked accounts
        ("collect", "instagram"),  # hashtags
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
        ("link", "instagram"),
        ("collect", "instagram"),
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

    assert [(r.kind, r.platform) for r in result.runs] == [
        ("link", "instagram"),
        ("collect", "instagram"),
        ("collect", "instagram"),
    ]
    assert fake_yt.calls == []
    assert result.post_locations == {"probable_us": 1, "likely_us": 1, "non_us": 1, "unverified": 1}
    assert not result.creator_locations


def test_platforms_without_keys_are_not_collected(session):
    assert enabled_platforms(make_settings()) == []
    assert enabled_platforms(make_settings(youtube_api_key="k")) == ["youtube"]
    assert enabled_platforms(ig_settings()) == ["instagram"]
    assert enabled_platforms(ig_settings(youtube_api_key="k")) == ["youtube", "instagram"]


# --- linked Instagram accounts and Gemini through the whole pipeline ------------------------


def link_in_descriptions(fake_yt, handle):
    """Every video of the fake channel mentions the same Instagram account."""
    for video in fake_yt.videos["items"]:
        video["snippet"]["description"] += f" Follow me: https://www.instagram.com/{handle}/"


def test_a_linked_instagram_account_is_collected_and_ranked_with_its_competitor(session):
    session.add(Keyword(term="life insurance agent", platform=None, active=True))
    session.commit()
    fake_yt, fake_ig = FakeYouTube(), FakeInstagram()
    link_in_descriptions(fake_yt, "jane_ig")
    fake_ig.add_account(
        "jane_ig",
        name="Jane Insurance",
        bio="Life insurance agent",
        followers=4200,
        pages=[[media("ig1", days=2, likes=300, comments=20), media("ig2", days=3, likes=90)]],
    )
    settings = ig_settings(youtube_api_key="k")

    runs = refresh(
        session,
        fake_yt.client(),
        settings,
        discover=True,
        now=NOW,
        instagram_client=fake_ig.client(),
    )

    link_run = next(r for r in runs if r.kind == "link")
    assert link_run.items_ok == 1
    account = session.scalars(select(Creator).where(Creator.handle == "jane_ig")).one()
    assert account.competitor_id is not None
    posts = {
        p.external_id: p for p in session.scalars(select(Post).where(Post.creator_id == account.id))
    }
    assert set(posts) == {"ig1", "ig2"}
    ranked = {
        s.post_id for s in session.scalars(select(PostScore).where(PostScore.window_days == 30))
    }
    assert posts["ig1"].id in ranked  # competitor posts are ranked like any other
    # The account has no evidence of its own, so it leans on its YouTube channel.
    assert account.location_status in {"likely_us", "unverified"}


def test_one_gemini_connection_labels_posts_and_reviews_accounts_under_one_rate_limit(session):
    from app.gemini_client import GeminiJson
    from tests.gemini_fake import Clock, FakeGemini

    session.add(Keyword(term="life insurance agent", platform=None, active=True))
    session.commit()
    gemini_fake, clock = FakeGemini(), Clock()
    gemini = GeminiJson(gemini_fake, "m", 10, sleep=clock.sleep, clock=clock.clock)

    runs = refresh(
        session,
        FakeYouTube().client(),
        make_settings(youtube_api_key="k"),
        discover=True,
        now=NOW,
        gemini=gemini,
    )

    label_run = next(r for r in runs if r.kind == "label")
    assert "labeled with gemini" in label_run.message
    assert {lab.labeler for lab in session.scalars(select(Label))} == {"gemini"}
    assert {lab.model for lab in session.scalars(select(Label))} == {"gemini-3.5-flash-lite"}
    prompts = [call.prompt for call in gemini_fake.calls]
    assert any('"post_id"' in prompt for prompt in prompts)  # labeling
    assert any('"creator_id"' in prompt for prompt in prompts)  # reviewing accounts
    assert len(clock.slept) == len(prompts) - 1  # every request after the first was spaced out


def test_when_gemini_fails_everything_still_gets_labeled_by_the_rules(session):
    from app.gemini_client import GeminiJson
    from tests.gemini_fake import Clock, FakeGemini

    session.add(Keyword(term="life insurance agent", platform=None, active=True))
    session.commit()
    clock = Clock()
    broken = GeminiJson(
        FakeGemini(lambda prompt: RuntimeError("quota exhausted")),
        "m",
        10,
        sleep=clock.sleep,
        clock=clock.clock,
    )

    runs = refresh(
        session, FakeYouTube().client(), make_settings(youtube_api_key="k"), discover=True,
        now=NOW, gemini=broken,
    )  # fmt: skip

    assert {lab.labeler for lab in session.scalars(select(Label))} == {"rules"}
    label_run = next(r for r in runs if r.kind == "label")
    assert "fell back to rules" in label_run.message
    assert "quota exhausted" in label_run.message
    assert [r.status for r in runs if r.kind == "rank"] == ["ok"]
