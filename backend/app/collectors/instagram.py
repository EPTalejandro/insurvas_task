"""Instagram hashtag collector: hashtag name -> hashtag id -> top posts.

The API gives no author for hashtag posts, so they are stored under one placeholder creator
per hashtag and have no competitor. The US check later reads each caption instead.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import runs
from app.collectors.instagram_parsers import parse_media
from app.collectors.posts import upsert_posts
from app.config import Settings
from app.httpclient import ApiError, get_json
from app.models import HASHTAG_KIND, Creator, Keyword, Run

GRAPH_API = "https://graph.facebook.com"
# Page sizes to try, largest first. The API fails with "reduce the amount of data" when a page
# is too big for its captions: 20+ never works, and 15 works only some of the time.
PAGE_SIZES = (15, 10, 5)
MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,like_count,comments_count,permalink,timestamp"
)


def instagram_enabled(settings: Settings) -> bool:
    return bool(settings.ig_access_token and settings.ig_user_id and settings.meta_graph_version)


def explain(error: ApiError) -> str:
    """A short message for the run log. Error bodies never contain the token."""
    if '"code":190' in str(error):
        return "Instagram access token expired or invalid (code 190): create a new token"
    return str(error)[:150]


def _root(settings: Settings) -> str:
    return f"{GRAPH_API}/{settings.meta_graph_version}"


def search_hashtag_id(client: httpx.Client, settings: Settings, tag: str) -> str | None:
    params = {"user_id": settings.ig_user_id, "q": tag, "access_token": settings.ig_access_token}
    data = get_json(client, f"{_root(settings)}/ig_hashtag_search", params, retries=1)
    found = data.get("data", [])
    return found[0]["id"] if found else None


def is_too_much_data(error: ApiError) -> bool:
    return error.status_code == 500 and "reduce the amount of data" in str(error)


def fetch_top_media_page(
    client: httpx.Client,
    settings: Settings,
    hashtag_id: str,
    page_size: int,
    after: str | None = None,
) -> dict[str, Any]:
    params = {
        "user_id": settings.ig_user_id,
        "fields": MEDIA_FIELDS,
        "limit": page_size,
        "access_token": settings.ig_access_token,
    }
    if after:
        params["after"] = after
    # No retries: a page that is too big fails the same way again, and takes 20+ seconds.
    return get_json(client, f"{_root(settings)}/{hashtag_id}/top_media", params, retries=0)


def _hashtag_creator(session: Session, tag: str, hashtag_id: str) -> Creator:
    """The placeholder account that owns a hashtag's posts."""
    external_id = f"hashtag:{hashtag_id}"
    creator = session.scalars(
        select(Creator).where(Creator.platform == "instagram", Creator.external_id == external_id)
    ).first()
    if creator is None:
        creator = Creator(
            platform="instagram",
            external_id=external_id,
            handle=f"#{tag}",
            name=f"#{tag} top posts",
            kind=HASHTAG_KIND,
            is_relevant=True,
            discovered_via=tag,
        )
        session.add(creator)
        session.flush()
    return creator


def _read_top_media(
    client: httpx.Client, settings: Settings, hashtag_id: str
) -> tuple[list[dict[str, Any]], str | None]:
    """Follow the pages. On an error, keep what was read and return the message."""
    items: dict[str, dict[str, Any]] = {}
    after = None
    size = 0  # index in PAGE_SIZES; once a smaller size is needed, keep it for the next pages
    for _ in range(settings.hashtag_max_pages):
        while True:
            try:
                page = fetch_top_media_page(client, settings, hashtag_id, PAGE_SIZES[size], after)
                break
            except ApiError as error:
                if is_too_much_data(error) and size < len(PAGE_SIZES) - 1:
                    size += 1
                    continue
                return list(items.values()), explain(error)
        for raw in page.get("data", []):
            if raw.get("id") and raw.get("permalink"):
                items[raw["id"]] = parse_media(raw)
        paging = page.get("paging", {})
        after = paging.get("cursors", {}).get("after") if "next" in paging else None
        if not after:
            break
    return list(items.values()), None


def collect_hashtags(
    session: Session, client: httpx.Client, settings: Settings, now: datetime | None = None
) -> Run:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.lookback_days)
    run = runs.start_run(session, "collect", "instagram")
    keywords = session.scalars(
        select(Keyword).where(Keyword.active, Keyword.platform == "instagram")
    ).all()

    ok = failed = saved = 0
    last_error = None
    for keyword in keywords:
        tag = keyword.term.lstrip("#")
        try:
            hashtag_id = search_hashtag_id(client, settings, tag)
        except ApiError as error:
            failed += 1
            last_error = explain(error)
            if "code 190" in last_error:
                break  # every other call would fail the same way
            continue
        if hashtag_id is None:
            failed += 1
            last_error = f"hashtag #{tag} not found"
            continue

        creator = _hashtag_creator(session, tag, hashtag_id)
        parsed, page_error = _read_top_media(client, settings, hashtag_id)
        # Top posts are not sorted by date: old ones are dropped, like in the YouTube collector.
        recent = [p for p in parsed if p["published_at"] and p["published_at"] >= cutoff]
        saved += upsert_posts(session, creator, recent, now, "instagram")
        if parsed or page_error is None:
            ok += 1
        if page_error:
            failed += 1
            last_error = page_error

    if failed == 0:
        status = runs.OK
    elif ok > 0:
        status = runs.PARTIAL
    else:
        status = runs.ERROR
    message = f"{saved} posts from {ok} hashtags" if keywords else "no hashtags configured"
    if last_error:
        message += f"; last error: {last_error}"
    return runs.finish_run(
        session, run, status=status, items_ok=ok, items_failed=failed, message=message
    )
