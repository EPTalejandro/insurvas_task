"""YouTube Data API calls and the `collect` step.

The API calls are thin wrappers (one request each) so tests can fake them with a MockTransport.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import runs
from app.collectors.youtube_parsers import parse_datetime, parse_video, uploads_playlist_id
from app.config import Settings
from app.httpclient import ApiError, get_json
from app.models import Competitor, Creator, Post, Run

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
SEARCH_COST = 100  # quota units; every other call we use costs 1
BATCH_SIZE = 50  # the API accepts at most 50 ids per request


def is_quota_error(error: ApiError) -> bool:
    return error.status_code == 403 and "quotaExceeded" in str(error)


def search_videos(
    client: httpx.Client,
    api_key: str,
    query: str,
    published_after: str,
    page_token: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "regionCode": "US",
        "relevanceLanguage": "en",
        "publishedAfter": published_after,
        "maxResults": BATCH_SIZE,
        "key": api_key,
    }
    if page_token:
        params["pageToken"] = page_token
    return get_json(client, f"{YOUTUBE_API}/search", params)


def fetch_channels(client: httpx.Client, api_key: str, channel_ids: list[str]) -> list[dict]:
    params = {"part": "snippet,statistics", "id": ",".join(channel_ids), "key": api_key}
    return get_json(client, f"{YOUTUBE_API}/channels", params).get("items", [])


def recent_video_ids(
    client: httpx.Client, api_key: str, playlist_id: str, cutoff: datetime, limit: int
) -> list[str]:
    """Ids of uploads newer than the cutoff. The playlist is newest first."""
    params = {
        "part": "contentDetails",
        "playlistId": playlist_id,
        "maxResults": min(limit, BATCH_SIZE),
        "key": api_key,
    }
    items = get_json(client, f"{YOUTUBE_API}/playlistItems", params).get("items", [])
    ids = []
    for item in items:
        details = item["contentDetails"]
        published = parse_datetime(details.get("videoPublishedAt"))
        if published and published >= cutoff:
            ids.append(details["videoId"])
    return ids


def fetch_videos(client: httpx.Client, api_key: str, video_ids: list[str]) -> list[dict]:
    params = {
        "part": "snippet,contentDetails,statistics",
        "id": ",".join(video_ids),
        "key": api_key,
    }
    return get_json(client, f"{YOUTUBE_API}/videos", params).get("items", [])


def upsert_posts(
    session: Session, creator: Creator, parsed: list[dict[str, Any]], now: datetime
) -> int:
    """Insert new posts and refresh metrics of known ones. Returns how many were written."""
    ids = [video["external_id"] for video in parsed]
    existing = {
        post.external_id: post
        for post in session.scalars(
            select(Post).where(Post.platform == "youtube", Post.external_id.in_(ids))
        )
    }
    for video in parsed:
        fields = {k: v for k, v in video.items() if k != "channel_id"}
        post = existing.get(video["external_id"])
        if post is None:
            post = Post(creator_id=creator.id, platform="youtube", **fields)
            session.add(post)
        else:
            for name, value in fields.items():
                setattr(post, name, value)
        post.last_collected_at = now
    session.commit()
    return len(parsed)


def collect_youtube(
    session: Session, client: httpx.Client, settings: Settings, now: datetime | None = None
) -> Run:
    """Collect recent uploads of every active competitor's YouTube channel.

    One broken channel never stops the run: it is counted as failed and we move on.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.lookback_days)
    run = runs.start_run(session, "collect", "youtube")
    creators = session.scalars(
        select(Creator)
        .join(Competitor, Creator.competitor_id == Competitor.id)
        .where(
            Creator.platform == "youtube",
            Creator.is_relevant,
            Competitor.status == "active",
        )
    ).all()

    accounts_ok = accounts_failed = posts = quota = 0
    last_error = None
    for creator in creators:
        playlist_id = uploads_playlist_id(creator.external_id)
        try:
            if playlist_id is None:
                raise ApiError(0, f"unexpected channel id for {creator.handle}")
            ids = recent_video_ids(
                client,
                settings.youtube_api_key,
                playlist_id,
                cutoff,
                settings.max_posts_per_account,
            )
            quota += 1
            parsed = []
            if ids:
                items = fetch_videos(client, settings.youtube_api_key, ids)
                quota += 1
                parsed = [video for item in items if (video := parse_video(item))]
            posts += upsert_posts(session, creator, parsed, now)
            accounts_ok += 1
        except ApiError as error:
            accounts_failed += 1
            last_error = str(error)
            if is_quota_error(error):
                break  # every later call would fail too

    if accounts_failed == 0:
        status = runs.OK
    elif accounts_ok > 0:
        status = runs.PARTIAL
    else:
        status = runs.ERROR
    message = f"{posts} posts from {accounts_ok} channels"
    if last_error:
        message += f"; last error: {last_error[:150]}"
    return runs.finish_run(
        session,
        run,
        status=status,
        items_ok=accounts_ok,
        items_failed=accounts_failed,
        quota_used=quota,
        message=message,
    )
