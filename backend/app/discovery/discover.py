"""The `discover` step: find YouTube channels of life insurance agents and agencies."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import runs
from app.collectors.youtube import (
    BATCH_SIZE,
    SEARCH_COST,
    fetch_channels,
    is_quota_error,
    search_videos,
)
from app.collectors.youtube_parsers import parse_channel
from app.config import Settings
from app.discovery.classify import classify_creator
from app.discovery.gemini_review import CreatorBrief, GeminiReviewer
from app.discovery.location import NON_US, assess_location
from app.discovery.selection import choose_new_active, discovery_score
from app.httpclient import ApiError
from app.models import Competitor, Creator, Keyword, Run

MAX_PAGES_PER_KEYWORD = 3


def _search_channel_ids(
    session: Session, client: httpx.Client, settings: Settings, now: datetime
) -> tuple[dict[str, str], int, int, str | None]:
    """Search every active keyword. Returns (channel_id -> keyword, quota used, failures, error)."""
    keywords = session.scalars(
        select(Keyword).where(
            Keyword.active, or_(Keyword.platform.is_(None), Keyword.platform == "youtube")
        )
    ).all()
    published_after = (now - timedelta(days=settings.lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Spread the quota budget over the keywords: a few pages each, but at least one.
    searches_allowed = settings.youtube_discovery_quota // SEARCH_COST
    pages = max(1, min(MAX_PAGES_PER_KEYWORD, searches_allowed // max(len(keywords), 1)))

    found: dict[str, str] = {}
    quota = failures = 0
    last_error = None
    for keyword in keywords:
        page_token = None
        for _ in range(pages):
            if quota + SEARCH_COST > settings.youtube_discovery_quota:
                return found, quota, failures, last_error
            try:
                data = search_videos(
                    client, settings.youtube_api_key, keyword.term, published_after, page_token
                )
            except ApiError as error:
                failures += 1
                last_error = str(error)
                if is_quota_error(error):
                    return found, quota, failures, last_error
                break  # skip the rest of this keyword
            quota += SEARCH_COST
            for item in data.get("items", []):
                found.setdefault(item["snippet"]["channelId"], keyword.term)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return found, quota, failures, last_error


def _second_opinion(session: Session, unsure: list[Creator], reviewer: GeminiReviewer) -> None:
    """Ask Gemini about the accounts the rules only guessed on. No answer: the guess stays."""
    briefs = [CreatorBrief(creator.id, creator.name, creator.bio) for creator in unsure]
    verdicts = reviewer.review(briefs)
    for creator in unsure:
        verdict = verdicts.get(creator.id)
        if verdict is None:
            continue
        sells_insurance = verdict.kind in ("agent", "agency")
        creator.kind = verdict.kind if sells_insurance else None
        creator.is_relevant = sells_insurance and creator.location_status != NON_US


def _upsert_creators(
    session: Session,
    channels: list[dict],
    found: dict[str, str],
    reviewer: GeminiReviewer | None = None,
) -> list[Creator]:
    existing = {
        creator.external_id: creator
        for creator in session.scalars(select(Creator).where(Creator.platform == "youtube"))
    }
    creators = []
    unsure: list[Creator] = []
    for fields in channels:
        creator = existing.get(fields["external_id"])
        is_new = creator is None
        if is_new:
            creator = Creator(
                platform="youtube",
                discovered_via=found.get(fields["external_id"]),
                **fields,
            )
            session.add(creator)
        else:
            for name, value in fields.items():
                setattr(creator, name, value)
        result = classify_creator(creator.name, creator.bio)
        creator.kind = result.kind
        creator.is_relevant = result.is_relevant
        # Known accounts without a country keep the status `update_locations` gave them
        # from their posts; discover only has the bio to go on.
        if is_new or creator.country:
            location = assess_location(creator.country, creator.bio, [])
            creator.location_status = location.status
            creator.location_evidence = location.evidence
        if creator.location_status == NON_US:
            creator.is_relevant = False  # never becomes a competitor
        creators.append(creator)
        if result.unsure:
            unsure.append(creator)
    session.flush()
    if reviewer is not None and unsure:
        _second_opinion(session, unsure, reviewer)
    return creators


def _link_competitors(session: Session, creators: list[Creator]) -> None:
    """Every relevant account without a competitor becomes a new candidate competitor."""
    for creator in creators:
        if creator.is_relevant and creator.competitor_id is None:
            competitor = Competitor(name=creator.name, kind=creator.kind, status="candidate")
            session.add(competitor)
            session.flush()
            creator.competitor_id = competitor.id
    session.flush()


def _activate_best_candidates(session: Session, max_competitors: int) -> None:
    """Keep the active competitors and fill the free slots with the best-scoring candidates."""
    competitors = session.scalars(
        select(Competitor).where(Competitor.status.in_(("active", "candidate")))
    ).all()
    for competitor in competitors:
        followers = sum(c.followers or 0 for c in competitor.creators)
        platforms = len({c.platform for c in competitor.creators})
        competitor.discovery_score = discovery_score(followers, platforms)

    active = [c for c in competitors if c.status == "active"]
    candidates = [(c.id, c.discovery_score) for c in competitors if c.status == "candidate"]
    chosen = set(choose_new_active(candidates, max_competitors - len(active)))
    for competitor in competitors:
        if competitor.id in chosen:
            competitor.status = "active"
    session.commit()


def discover_youtube(
    session: Session,
    client: httpx.Client,
    settings: Settings,
    now: datetime | None = None,
    reviewer: GeminiReviewer | None = None,
) -> Run:
    now = now or datetime.now(UTC)
    run = runs.start_run(session, "discover", "youtube")

    found, quota, failures, last_error = _search_channel_ids(session, client, settings, now)

    channels: list[dict] = []
    channel_ids = list(found)
    for start in range(0, len(channel_ids), BATCH_SIZE):
        batch = channel_ids[start : start + BATCH_SIZE]
        try:
            channels += [
                parse_channel(item)
                for item in fetch_channels(client, settings.youtube_api_key, batch)
            ]
            quota += 1
        except ApiError as error:
            failures += 1
            last_error = str(error)
            if is_quota_error(error):
                break

    creators = _upsert_creators(session, channels, found, reviewer)
    _link_competitors(session, creators)
    _activate_best_candidates(session, settings.max_competitors)

    relevant = sum(1 for creator in creators if creator.is_relevant)
    if failures == 0:
        status = runs.OK
    elif creators:
        status = runs.PARTIAL
    else:
        status = runs.ERROR
    message = f"{len(creators)} channels seen, {relevant} relevant"
    if last_error:
        message += f"; last error: {last_error[:150]}"
    return runs.finish_run(
        session,
        run,
        status=status,
        items_ok=len(creators),
        items_failed=failures,
        quota_used=quota,
        message=message,
    )
