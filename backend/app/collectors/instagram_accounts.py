"""Instagram accounts of the competitors: find them (linking) and collect their posts.

Instagram has no search for accounts, so the only way in is a handle found on YouTube. See
`app.discovery.linking` for the rules; this module does the network and database work around them.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import runs
from app.collectors.instagram import (
    ACCOUNT_PAGE_SIZES,
    explain,
    fetch_account_page,
    fetch_profile,
    is_invalid_account,
    is_too_much_data,
)
from app.collectors.instagram_parsers import parse_media
from app.collectors.posts import upsert_posts
from app.config import Settings
from app.discovery.classify import classify_creator
from app.discovery.linking import (
    Candidate,
    LinkDecision,
    candidates_from,
    choose_handle,
    points_back,
    resolve_conflicts,
)
from app.httpclient import ApiError
from app.models import HASHTAG_KIND, Competitor, Creator, Post, Run

MAX_CANDIDATES = 3  # profiles fetched per competitor while deciding
TOKEN_ERROR = "code 190"


def _instagram_creators(session: Session) -> list[Creator]:
    """Instagram accounts of active competitors (not the hashtag placeholders)."""
    return list(
        session.scalars(
            select(Creator)
            .join(Competitor, Creator.competitor_id == Competitor.id)
            .where(
                Creator.platform == "instagram",
                Creator.kind != HASHTAG_KIND,
                Creator.is_relevant,
                Competitor.status == "active",
            )
        )
    )


def _unlinked_competitors(session: Session) -> list[Competitor]:
    """Active competitors that have a YouTube channel and no Instagram account yet."""
    with_instagram = select(Creator.competitor_id).where(
        Creator.platform == "instagram", Creator.competitor_id.is_not(None)
    )
    return list(
        session.scalars(
            select(Competitor).where(
                Competitor.status == "active", Competitor.id.not_in(with_instagram)
            )
        )
    )


def _youtube_texts(session: Session, channel: Creator) -> list[str | None]:
    """Where a channel's Instagram links would be: its bio and its video descriptions."""
    descriptions = session.scalars(select(Post.text).where(Post.creator_id == channel.id))
    return [channel.bio, *descriptions]


def _check_candidates(
    client: httpx.Client,
    settings: Settings,
    channel: Creator,
    candidates: list[Candidate],
    profiles: dict[str, dict[str, Any]],
) -> tuple[list[Candidate], set[str], str | None]:
    """Fetch each candidate's profile. Returns (usable candidates, confirmed handles, error).

    A handle that is not a professional account is simply dropped. Any other error means we
    do not have the full picture, so the caller must not decide for this channel.
    """
    usable: list[Candidate] = []
    confirmed: set[str] = set()
    for candidate in candidates:
        try:
            profile = profiles.get(candidate.handle) or fetch_profile(
                client, settings, candidate.handle
            )
        except ApiError as error:
            if is_invalid_account(error):
                continue
            return usable, confirmed, explain(error)
        profiles[candidate.handle] = profile
        usable.append(candidate)
        bio, website = profile.get("biography"), profile.get("website")
        if points_back(bio, website, channel.handle, channel.external_id):
            confirmed.add(candidate.handle)
    return usable, confirmed, None


def link_instagram_accounts(session: Session, client: httpx.Client, settings: Settings) -> Run:
    """Link each unlinked competitor to its Instagram account when the evidence is clear."""
    run = runs.start_run(session, "link", "instagram")
    decisions: dict[int, LinkDecision] = {}
    profiles: dict[str, dict[str, Any]] = {}
    failed = 0
    last_error = None

    competitors = _unlinked_competitors(session)
    for competitor in competitors:
        channel = session.scalars(
            select(Creator).where(
                Creator.competitor_id == competitor.id, Creator.platform == "youtube"
            )
        ).first()
        if channel is None:
            continue
        found = candidates_from(_youtube_texts(session, channel))[:MAX_CANDIDATES]
        usable, confirmed, error = _check_candidates(client, settings, channel, found, profiles)
        if error:
            failed += 1
            last_error = error
            if TOKEN_ERROR in error:
                break  # every other call would fail the same way
            continue  # incomplete information: do not decide for this competitor
        # Decide among ALL the candidates: if the front-runner cannot be read (not a professional
        # account), a weaker readable one must not take its place.
        decision = choose_handle(found, confirmed)
        if decision.handle and decision.handle not in {c.handle for c in usable}:
            decision = LinkDecision(
                None, f"@{decision.handle} cannot be read (not a professional account)"
            )
        decisions[competitor.id] = decision

    linked = []
    skipped = []
    taken = set(session.scalars(select(Creator.external_id).where(Creator.platform == "instagram")))
    for competitor_id, decision in resolve_conflicts(decisions).items():
        competitor = session.get(Competitor, competitor_id)
        reason = decision.reason
        if decision.handle:
            profile = profiles[decision.handle]
            name = profile.get("name") or decision.handle
            if classify_creator(name, profile.get("biography")).reason == "insurance carrier":
                reason = f"@{decision.handle} looks like an insurance carrier"
            elif decision.handle in taken:
                reason = f"@{decision.handle} is already linked to another competitor"
            else:
                session.add(
                    Creator(
                        competitor_id=competitor_id,
                        platform="instagram",
                        external_id=decision.handle,
                        handle=decision.handle,
                        name=name,
                        url=f"https://www.instagram.com/{decision.handle}/",
                        bio=profile.get("biography"),
                        followers=profile.get("followers_count"),
                        kind=competitor.kind,
                        is_relevant=True,
                        discovered_via=f"YouTube links: {decision.reason}",
                    )
                )
                taken.add(decision.handle)
                linked.append(f"@{decision.handle}")
                continue
        skipped.append(f"{competitor.name}: {reason}")
    session.commit()

    # Which competitors were left out is the interesting part, so it goes in the message.
    message = f"{len(linked)} linked of {len(competitors)} competitors"
    if linked:
        message += f" ({', '.join(linked)})"
    if skipped:
        message += f"; not linked: {len(skipped)}"
    if last_error:
        message += f"; last error: {last_error}"
    status = runs.ERROR if (failed and not linked) else runs.PARTIAL if failed else runs.OK
    return runs.finish_run(
        session, run, status=status, items_ok=len(linked), items_failed=failed, message=message
    )


def _read_account_media(
    client: httpx.Client, settings: Settings, handle: str, cutoff: datetime
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The profile and the posts newer than the cutoff, following pages until old posts begin."""
    profile: dict[str, Any] | None = None
    posts: dict[str, dict[str, Any]] = {}
    after = None
    size = 0
    while len(posts) < settings.max_posts_per_account:
        try:
            page = fetch_account_page(client, settings, handle, ACCOUNT_PAGE_SIZES[size], after)
        except ApiError as error:
            if is_too_much_data(error) and size < len(ACCOUNT_PAGE_SIZES) - 1:
                size += 1
                continue
            raise
        profile = page
        media = page.get("media", {})
        reached_old_posts = False
        for raw in media.get("data", []):
            if not (raw.get("id") and raw.get("permalink")):
                continue
            parsed = parse_media(raw)
            if parsed["published_at"] and parsed["published_at"] >= cutoff:
                posts[parsed["external_id"]] = parsed
            else:
                reached_old_posts = True  # newest first: everything after this is older
        paging = media.get("paging", {})
        after = paging.get("cursors", {}).get("after") if "next" in paging else None
        if reached_old_posts or not after:
            break
    return profile, list(posts.values())[: settings.max_posts_per_account]


def collect_instagram_accounts(
    session: Session, client: httpx.Client, settings: Settings, now: datetime | None = None
) -> Run:
    """Collect the recent posts of every linked account. One bad account never stops the run."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.lookback_days)
    run = runs.start_run(session, "collect", "instagram")
    creators = _instagram_creators(session)

    ok = failed = saved = 0
    last_error = None
    for creator in creators:
        try:
            profile, posts = _read_account_media(client, settings, creator.handle, cutoff)
        except ApiError as error:
            failed += 1
            if is_invalid_account(error):
                # Not a professional account (any more): stop asking about it.
                creator.is_relevant = False
                last_error = f"@{creator.handle} cannot be read (not a professional account)"
                session.commit()
                continue
            last_error = explain(error)
            if TOKEN_ERROR in last_error:
                break
            continue
        if profile:
            creator.followers = profile.get("followers_count", creator.followers)
            creator.bio = profile.get("biography", creator.bio)
            creator.name = profile.get("name") or creator.name
        saved += upsert_posts(session, creator, posts, now, "instagram")
        ok += 1

    if failed == 0:
        status = runs.OK
    elif ok > 0:
        status = runs.PARTIAL
    else:
        status = runs.ERROR
    message = (
        f"accounts: {saved} posts from {ok} accounts" if creators else "accounts: none linked yet"
    )
    if last_error:
        message += f"; last error: {last_error}"
    return runs.finish_run(
        session, run, status=status, items_ok=ok, items_failed=failed, message=message
    )
