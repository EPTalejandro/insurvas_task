"""Pure functions that turn Instagram Graph API JSON into plain dicts."""

from typing import Any

from app.collectors.youtube_parsers import parse_datetime, to_int

FORMATS = {"IMAGE": "image", "CAROUSEL_ALBUM": "carousel", "VIDEO": "video"}


def media_format(media_type: str | None, product_type: str | None) -> str | None:
    # A Reel is a VIDEO whose product type is REELS; plain videos stay "video".
    if product_type == "REELS":
        return "reel"
    return FORMATS.get(media_type or "")


def parse_media(item: dict[str, Any]) -> dict[str, Any]:
    """One hashtag media item -> post fields."""
    return {
        "external_id": item["id"],
        "url": item["permalink"],
        "title": None,  # Instagram has only a caption, which goes in `text`
        "text": item.get("caption") or None,
        "published_at": parse_datetime(item.get("timestamp")),
        "format": media_format(item.get("media_type"), item.get("media_product_type")),
        "thumbnail_url": None,  # media_url links expire after a few days, so we skip them
        # Unknown stays None: a hidden like count is missing from the response.
        "views": None,  # not available outside Business Discovery
        "likes": to_int(item.get("like_count")),
        "comments": to_int(item.get("comments_count")),
        "shares": None,
    }
