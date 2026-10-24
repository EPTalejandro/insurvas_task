from datetime import UTC, datetime

from sqlalchemy import select

from app.collectors.youtube import collect_youtube
from app.config import Settings
from app.models import Competitor, Creator, Post
from tests.youtube_fake import FakeYouTube

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, youtube_api_key="test-key", **overrides)


def add_creator(session, channel_id: str, status: str = "active") -> Creator:
    competitor = Competitor(name=channel_id, kind="agent", status=status)
    creator = Creator(
        competitor=competitor,
        platform="youtube",
        external_id=channel_id,
        handle=f"@{channel_id}",
        name=channel_id,
    )
    session.add(creator)
    session.commit()
    return creator


def run_collect(session, fake: FakeYouTube, **settings):
    return collect_youtube(session, fake.client(), make_settings(**settings), now=NOW)


def test_collect_stores_recent_posts_with_formats_and_unknown_metrics(session):
    add_creator(session, "UCagent0001")
    fake = FakeYouTube()

    run = run_collect(session, fake)

    posts = {p.external_id: p for p in session.scalars(select(Post))}
    assert set(posts) == {"vid_short", "vid_long"}  # vid_old is outside the 90 days
    short, long = posts["vid_short"], posts["vid_long"]
    assert (short.format, long.format) == ("short_video", "long_video")
    assert short.title == "Don't buy term life until you watch this"
    assert short.likes is None
    assert short.views == 12000
    assert long.likes == 297
    assert run.status == "ok"
    assert (run.items_ok, run.quota_used) == (1, 2)  # playlistItems + videos


def test_collect_twice_refreshes_metrics_without_duplicates(session):
    add_creator(session, "UCagent0001")
    fake = FakeYouTube()
    run_collect(session, fake)

    fake.videos["items"][0]["statistics"]["viewCount"] = "99999"
    run_collect(session, fake)

    posts = session.scalars(select(Post)).all()
    assert len(posts) == 2
    assert {p.external_id: p.views for p in posts}["vid_short"] == 99999


def test_collect_only_reads_active_competitors(session):
    add_creator(session, "UCcandidate1", status="candidate")
    fake = FakeYouTube()

    run = run_collect(session, fake)

    assert fake.calls == []
    assert run.items_ok == 0
    assert session.scalars(select(Post)).all() == []


def test_one_broken_channel_does_not_stop_the_run(session):
    add_creator(session, "UCbroken0001")
    add_creator(session, "UCagent0001")
    fake = FakeYouTube()
    fake.failing_playlists.add("UUbroken0001")

    run = run_collect(session, fake)

    assert run.status == "partial"
    assert (run.items_ok, run.items_failed) == (1, 1)
    assert len(session.scalars(select(Post)).all()) == 2


def test_lookback_days_controls_which_posts_are_kept(session):
    add_creator(session, "UCagent0001")
    fake = FakeYouTube()

    run_collect(session, fake, lookback_days=7)  # vid_short is 4 days old, vid_long is 14

    assert [p.external_id for p in session.scalars(select(Post))] == ["vid_short"]
