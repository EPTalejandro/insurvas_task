"""Searches started from the Search tab: create them, find the due ones and run them.

A search is a list of steps run in a fixed order. Each step calls the same function the CLI
uses. While a step runs, its progress is kept in memory (not in the database): it changes many
times a second, and committing it would also commit the step's half-done work (rank, for
example, rolls back to the old scores if it fails). Statuses and results are saved per step.
"""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import runs
from app.collectors.instagram import collect_hashtags
from app.collectors.instagram_accounts import collect_instagram_accounts, link_instagram_accounts
from app.collectors.youtube import collect_youtube
from app.config import Settings
from app.discovery.discover import discover_youtube
from app.discovery.gemini_review import GeminiReviewer
from app.discovery.keywords import normalize_keyword
from app.discovery.location import update_locations, update_post_locations
from app.gemini_client import GeminiJson, make_gemini
from app.httpclient import make_client
from app.labeling.service import label_posts
from app.models import Job, JobStep, Run
from app.pipeline import INSTAGRAM_TIMEOUT, enabled_platforms, pick_labeler
from app.ranking.scoring import as_utc
from app.ranking.service import rank_all

# The steps a search can have, in the order they run.
STEPS = {
    "discover": "Discover YouTube channels",
    "youtube": "Collect YouTube videos",
    "instagram_accounts": "Collect Instagram accounts",
    "hashtags": "Collect Instagram hashtags",
    "label": "Label posts",
    "rank": "Rank posts and competitors",
}
PLATFORM_OF = {
    "discover": "youtube",
    "youtube": "youtube",
    "instagram_accounts": "instagram",
    "hashtags": "instagram",
}
COLLECT_STEPS = ("youtube", "instagram_accounts", "hashtags")

SCHEDULED = "scheduled"
PENDING = "pending"
SKIPPED = "skipped"
# A time picked in the browser a few seconds ago is still "now", not the past.
PAST_GRACE = timedelta(minutes=1)
INTERRUPTED = "the server stopped during this search"


# --- creating a search ---------------------------------------------------------------------------


def clean_terms(terms: list[str], platform: str | None) -> list[str]:
    """Each term as the Sources tab stores it, without repeats. Raises ValueError."""
    cleaned: list[str] = []
    for term in terms:
        term = normalize_keyword(term, platform)
        if term.lower() not in {t.lower() for t in cleaned}:
            cleaned.append(term)
    return cleaned


def validate_new_job(
    steps: list[str],
    run_at: datetime | None,
    youtube_terms: list[str],
    hashtags: list[str],
    now: datetime,
) -> None:
    """Raises ValueError with a message for the user when the search cannot run."""
    if not steps:
        raise ValueError("pick at least one step")
    unknown = [step for step in steps if step not in STEPS]
    if unknown:
        raise ValueError(f"unknown step '{unknown[0]}'; steps are: {', '.join(STEPS)}")
    if "discover" in steps and not youtube_terms:
        raise ValueError("discover needs at least one YouTube search term")
    if "hashtags" in steps and not hashtags:
        raise ValueError("collecting hashtags needs at least one hashtag")
    if run_at is not None and as_utc(run_at) < as_utc(now) - PAST_GRACE:
        raise ValueError("that time has already passed")


def _naive(value: datetime) -> datetime:
    """SQLite has no time zones: we store naive UTC, like every other table."""
    return as_utc(value).replace(tzinfo=None)


def create_job(
    session: Session,
    steps: list[str],
    run_at: datetime | None,
    youtube_terms: list[str],
    hashtags: list[str],
    now: datetime | None = None,
) -> Job:
    """Check and save a new search. run_at=None means "start now". Raises ValueError."""
    now = now or datetime.now(UTC)
    youtube_terms = clean_terms(youtube_terms, None)
    hashtags = clean_terms(hashtags, "instagram")
    validate_new_job(steps, run_at, youtube_terms, hashtags, now)
    ordered = [key for key in STEPS if key in steps]  # fixed order, no repeats
    job = Job(
        status=SCHEDULED,
        run_at=_naive(run_at or now),
        # Terms are kept only for the step that uses them.
        youtube_terms=youtube_terms if "discover" in ordered else [],
        hashtags=hashtags if "hashtags" in ordered else [],
        steps=[JobStep(position=i, step=key) for i, key in enumerate(ordered)],
    )
    session.add(job)
    session.commit()
    return job


# --- finding work --------------------------------------------------------------------------------


def next_due_job(session: Session, now: datetime | None = None) -> Job | None:
    """The oldest scheduled search whose time has come."""
    now = now or datetime.now(UTC)
    return session.scalars(
        select(Job)
        .where(Job.status == SCHEDULED, Job.run_at <= _naive(now))
        .order_by(Job.run_at, Job.id)
    ).first()


def mark_interrupted(session: Session) -> int:
    """At startup: a search still "running" died with the last server, so it failed."""
    jobs = session.scalars(select(Job).where(Job.status == runs.RUNNING)).all()
    for job in jobs:
        for step in job.steps:
            if step.status in (runs.RUNNING, PENDING):
                step.status = runs.ERROR
                step.message = INTERRUPTED
        job.status = runs.ERROR
        job.message = INTERRUPTED
        job.finished_at = datetime.now(UTC)
    session.commit()
    return len(jobs)


# --- live progress -------------------------------------------------------------------------------

# step id -> (done, total, detail), only while that step runs. The API reads it from here.
_live: dict[int, tuple[int, int, str | None]] = {}


def live_progress(step_id: int) -> tuple[int, int, str | None] | None:
    return _live.get(step_id)


def _reporter(step: JobStep, detail: str | None = None) -> runs.Progress:
    def report(done: int, total: int) -> None:
        _live[step.id] = (done, total, detail)

    return report


# --- running a search ----------------------------------------------------------------------------


def combined_status(statuses: list[str]) -> str:
    """ok if everything worked (or was skipped), error if nothing did, partial otherwise."""
    if all(status in (runs.OK, SKIPPED) for status in statuses):
        return runs.OK
    if not any(status in (runs.OK, runs.PARTIAL) for status in statuses):
        return runs.ERROR
    return runs.PARTIAL


def _run_step(
    session: Session,
    job: Job,
    step: JobStep,
    client: httpx.Client,
    instagram_client: httpx.Client | None,
    settings: Settings,
    now: datetime | None,
    gemini: GeminiJson | None,
    reviewer: GeminiReviewer | None,
) -> list[Run]:
    """Call the pipeline function(s) of one step."""
    if step.step == "discover":
        return [
            discover_youtube(
                session,
                client,
                settings,
                now,
                reviewer,
                terms=job.youtube_terms,
                progress=_reporter(step),
            )
        ]
    if step.step == "youtube":
        return [collect_youtube(session, client, settings, now, progress=_reporter(step))]
    if step.step == "instagram_accounts":
        assert instagram_client is not None
        # Two parts, one bar: the detail text tells which part is running.
        linked = link_instagram_accounts(
            session, instagram_client, settings, progress=_reporter(step, "linking")
        )
        collected = collect_instagram_accounts(
            session, instagram_client, settings, now, progress=_reporter(step, "collecting")
        )
        return [linked, collected]
    if step.step == "hashtags":
        assert instagram_client is not None
        return [
            collect_hashtags(
                session,
                instagram_client,
                settings,
                now,
                terms=job.hashtags,
                progress=_reporter(step),
            )
        ]
    if step.step == "label":
        return [label_posts(session, pick_labeler(settings, gemini), progress=_reporter(step))]
    if step.step == "rank":
        return [rank_all(session, now, progress=_reporter(step))]
    raise ValueError(f"unknown step {step.step}")


def _check_locations(
    session: Session, step: JobStep, instagram_ran: bool, reviewer: GeminiReviewer | None
) -> None:
    """What `pipeline.collect_step` does after collecting: decide which posts are US-based."""
    done, total, _ = _live.get(step.id, (0, 0, None))
    _live[step.id] = (done, total, "checking locations")
    if instagram_ran:
        update_post_locations(session)
    update_locations(session, reviewer)


def run_job(
    session: Session,
    job: Job,
    client: httpx.Client,
    settings: Settings,
    now: datetime | None = None,
    gemini: GeminiJson | None = None,
    instagram_client: httpx.Client | None = None,
) -> Job:
    """Run every step in order. A failing step is marked and the next ones still run."""
    job.status = runs.RUNNING
    job.started_at = datetime.now(UTC)
    session.commit()

    enabled = enabled_platforms(settings)
    gemini = gemini or make_gemini(settings)  # one connection, so the per-minute limit holds
    reviewer = GeminiReviewer(gemini) if gemini else None
    # A step of a platform without keys is skipped; label and rank always run.
    runnable = [s.step for s in job.steps if PLATFORM_OF.get(s.step, "") in ("", *enabled)]
    collecting = [key for key in runnable if key in COLLECT_STEPS]
    instagram_ran = any(PLATFORM_OF.get(key) == "instagram" for key in collecting)
    own_client = None
    if instagram_ran and instagram_client is None:
        # Instagram hashtag pages are slow, so they get a longer timeout.
        own_client = instagram_client = make_client(INSTAGRAM_TIMEOUT)

    try:
        for step in job.steps:
            if step.step not in runnable:
                step.status = SKIPPED
                step.message = f"{PLATFORM_OF[step.step]} has no keys in .env"
                session.commit()
                continue
            step.status = runs.RUNNING
            session.commit()
            try:
                done = _run_step(
                    session, job, step, client, instagram_client, settings, now, gemini, reviewer
                )
                if collecting and step.step == collecting[-1]:
                    _check_locations(session, step, instagram_ran, reviewer)
                step.status = combined_status([run.status for run in done])
                step.message = " | ".join(run.message for run in done if run.message)
            except Exception as error:  # one broken step never stops the search
                session.rollback()
                step.status = runs.ERROR
                step.message = str(error)[:200]
            live = _live.pop(step.id, None)
            step.done, step.total = (live[0], live[1]) if live else (0, 0)
            if step.status != runs.ERROR:
                step.done = step.total  # the last item finished after the last report
            session.commit()
    finally:
        if own_client is not None:
            own_client.close()

    statuses = [step.status for step in job.steps]
    job.status = combined_status(statuses)
    worked = sum(status in (runs.OK, runs.PARTIAL) for status in statuses)
    job.message = f"{worked} of {len(statuses)} steps worked"
    if SKIPPED in statuses:
        job.message += f", {statuses.count(SKIPPED)} skipped"
    job.finished_at = datetime.now(UTC)
    session.commit()
    return job
