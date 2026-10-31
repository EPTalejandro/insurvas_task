from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import jobs
from app.config import Settings
from app.models import Job, Keyword, Post, Run
from tests.instagram_fake import FakeInstagram
from tests.instagram_fake import make_settings as make_ig_settings
from tests.youtube_fake import FakeYouTube

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def new_job(session, steps, *, run_at=None, youtube_terms=(), hashtags=()):
    return jobs.create_job(
        session, list(steps), run_at, list(youtube_terms), list(hashtags), now=NOW
    )


# --- creating ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("steps", "run_at", "youtube_terms", "hashtags", "message"),
    [
        ([], None, [], [], "pick at least one step"),
        (["scrape"], None, [], [], "unknown step 'scrape'"),
        (["discover"], None, [], [], "discover needs at least one YouTube search term"),
        (["hashtags"], None, [], [], "collecting hashtags needs at least one hashtag"),
        (["rank"], NOW - timedelta(minutes=5), [], [], "that time has already passed"),
    ],
)
def test_a_search_that_cannot_run_is_refused(steps, run_at, youtube_terms, hashtags, message):
    with pytest.raises(ValueError, match=message):
        jobs.validate_new_job(steps, run_at, youtube_terms, hashtags, NOW)


def test_a_time_a_few_seconds_ago_still_counts_as_now():
    jobs.validate_new_job(["rank"], NOW - timedelta(seconds=20), [], [], NOW)


def test_steps_are_stored_in_pipeline_order_and_terms_only_where_used(session):
    job = new_job(
        session, ["rank", "label", "rank", "youtube"], youtube_terms=["agent"], hashtags=["#IUL"]
    )

    assert [step.step for step in job.steps] == ["youtube", "label", "rank"]
    assert all(step.status == "pending" for step in job.steps)
    assert (job.status, job.youtube_terms, job.hashtags) == ("scheduled", [], [])


def test_terms_are_cleaned_like_the_sources_tab_does(session):
    job = new_job(
        session,
        ["discover", "hashtags"],
        youtube_terms=["  life   insurance ", "Life Insurance"],
        hashtags=["#IUL", "iul", "annuity"],
    )

    assert job.youtube_terms == ["life insurance"]
    assert job.hashtags == ["iul", "annuity"]


def test_a_bad_hashtag_is_refused(session):
    with pytest.raises(ValueError, match="one word"):
        new_job(session, ["hashtags"], hashtags=["life insurance"])


# --- finding work ------------------------------------------------------------------------------


def test_only_scheduled_searches_whose_time_has_come_are_due(session):
    later = new_job(session, ["rank"], run_at=NOW + timedelta(hours=1))
    first = new_job(session, ["rank"], run_at=NOW)
    finished = new_job(session, ["rank"])
    finished.status = "ok"
    session.commit()

    assert jobs.next_due_job(session, NOW) == first
    first.status = "ok"
    session.commit()
    assert jobs.next_due_job(session, NOW) is None
    assert jobs.next_due_job(session, NOW + timedelta(hours=2)) == later


def test_a_search_left_running_by_a_stopped_server_becomes_an_error(session):
    job = new_job(session, ["label", "rank"])
    job.status = "running"
    job.steps[0].status = "ok"
    job.steps[1].status = "running"
    session.commit()

    assert jobs.mark_interrupted(session) == 1

    assert job.status == "error"
    assert [step.status for step in job.steps] == ["ok", "error"]
    assert job.steps[1].message == jobs.INTERRUPTED


# --- running -----------------------------------------------------------------------------------


def test_a_full_youtube_search_runs_every_step(session):
    job = new_job(
        session, ["discover", "youtube", "label", "rank"], youtube_terms=["life insurance agent"]
    )
    fake = FakeYouTube()

    jobs.run_job(session, job, fake.client(), make_settings(youtube_api_key="k"), NOW)

    assert job.status == "ok"
    assert [step.status for step in job.steps] == ["ok"] * 4
    # Every bar ends full, and the progress kept in memory is gone.
    assert all(step.done == step.total for step in job.steps)
    assert job.steps[0].total == 1  # one search term
    assert job.steps[3].total == 3  # three windows
    assert jobs._live == {}
    assert session.scalars(select(Post)).all()
    assert job.started_at is not None and job.finished_at is not None


def test_the_picked_terms_are_searched_not_the_active_ones(session):
    session.add(Keyword(term="active term", platform=None, active=True))
    session.commit()
    job = new_job(session, ["discover"], youtube_terms=["picked term"])
    fake = FakeYouTube()

    jobs.run_job(session, job, fake.client(), make_settings(youtube_api_key="k"), NOW)

    assert [params["q"] for path, params in fake.calls if path == "/search"] == ["picked term"]


def test_hashtags_use_the_picked_tags(session):
    job = new_job(session, ["hashtags"], hashtags=["iul"])
    fake = FakeInstagram()

    youtube = FakeYouTube().client()
    jobs.run_job(session, job, youtube, make_ig_settings(), NOW, instagram_client=fake.client())

    assert fake.queries() == ["iul"]
    assert job.steps[0].status == "ok"


def test_steps_of_a_platform_without_keys_are_skipped(session):
    job = new_job(session, ["youtube", "instagram_accounts", "rank"])

    jobs.run_job(session, job, FakeYouTube().client(), make_settings(), NOW)

    assert [step.status for step in job.steps] == ["skipped", "skipped", "ok"]
    assert job.steps[0].message == "youtube has no keys in .env"
    assert job.status == "ok"
    assert job.message == "1 of 3 steps worked, 2 skipped"


def test_a_step_that_breaks_does_not_stop_the_next_ones(session, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs, "collect_youtube", broken)
    job = new_job(session, ["youtube", "label", "rank"])

    jobs.run_job(session, job, FakeYouTube().client(), make_settings(youtube_api_key="k"), NOW)

    assert [step.status for step in job.steps] == ["error", "ok", "ok"]
    assert job.steps[0].message == "boom"
    assert job.status == "partial"
    assert session.scalars(select(Run).where(Run.kind == "rank")).all()


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["ok", "skipped"], "ok"),
        (["ok", "partial"], "partial"),
        (["ok", "error"], "partial"),
        (["error", "skipped"], "error"),
        (["skipped"], "ok"),
    ],
)
def test_combined_status(statuses, expected):
    assert jobs.combined_status(statuses) == expected


def test_jobs_table_keeps_the_terms_as_lists(session):
    new_job(session, ["discover"], youtube_terms=["a b"])
    session.expire_all()

    assert session.scalars(select(Job)).one().youtube_terms == ["a b"]
