"""Pure functions that turn YouTube API JSON into plain dicts. No network, no database."""

import html
import re
from datetime import UTC, datetime
from typing import Any

# The API has no "is a Short" flag, so we use the duration: Shorts are at most 3 minutes.
SHORT_MAX_SECONDS = 180

_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_iso_duration(value: str | None) -> int | None:
    """'PT19M4S' -> 1144. Returns None when the text is not an ISO 8601 duration."""
    if not value:
        return None
    match = _DURATION.match(value)
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def video_format(duration_s: int | None) -> str | None:
    if duration_s is None:
        return None
    return "short_video" if duration_s <= SHORT_MAX_SECONDS else "long_video"


def to_int(value: Any) -> int | None:
    """The API sends counts as strings, and leaves them out when hidden."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return None


def best_thumbnail(thumbnails: dict[str, Any]) -> str | None:
    for size in ("maxres", "standard", "high", "medium", "default"):
        if size in thumbnails:
            return thumbnails[size].get("url")
    return None


def uploads_playlist_id(channel_id: str) -> str | None:
    """Every channel has a playlist with all its uploads: same id with 'UC' replaced by 'UU'.

    Reading it costs 1 quota unit, while search.list costs 100.
    """
    if channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return None


def parse_video(item: dict[str, Any]) -> dict[str, Any] | None:
    """One videos.list item -> post fields. None for live or upcoming streams."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    if snippet.get("liveBroadcastContent") in ("live", "upcoming"):
        return None  # not a finished post yet

    video_id = item["id"]
    duration = parse_iso_duration(item.get("contentDetails", {}).get("duration"))
    return {
        "external_id": video_id,
        "channel_id": snippet.get("channelId"),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        # Titles arrive HTML-escaped (It&#39;s), so they are unescaped before storing.
        "title": html.unescape(snippet.get("title", "")) or None,
        "text": snippet.get("description") or None,
        "published_at": parse_datetime(snippet.get("publishedAt")),
        "format": video_format(duration),
        "thumbnail_url": best_thumbnail(snippet.get("thumbnails", {})),
        # Unknown stays None: likes and comments can be hidden by the creator.
        "views": to_int(stats.get("viewCount")),
        "likes": to_int(stats.get("likeCount")),
        "comments": to_int(stats.get("commentCount")),
        "shares": None,  # YouTube does not expose shares
    }


def parse_channel(item: dict[str, Any]) -> dict[str, Any]:
    """One channels.list item -> creator fields."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    channel_id = item["id"]
    custom_url = snippet.get("customUrl")  # usually "@handle"
    hidden = stats.get("hiddenSubscriberCount", False)

    if custom_url and custom_url.startswith("@"):
        url = f"https://www.youtube.com/{custom_url}"
    else:
        url = f"https://www.youtube.com/channel/{channel_id}"

    return {
        "external_id": channel_id,
        "handle": custom_url or snippet.get("title", ""),
        "name": snippet.get("title", ""),
        "url": url,
        "bio": snippet.get("description") or None,
        "country": snippet.get("country"),  # optional: only set when the owner chose one
        "followers": None if hidden else to_int(stats.get("subscriberCount")),
    }
