"""Pure functions that turn Instagram Graph API JSON into plain dicts."""

from typing import Any

from app.collectors.youtube_parsers import parse_datetime, to_int

FORMATS = {"IMAGE": "image", "CAROUSEL_ALBUM": "carousel", "VIDEO": "video"}


def media_format(media_type: str | None, product_type: str | None) -> str | None:
    # A Reel is a VIDEO whose product type is REELS; plain videos stay "video".
    if product_type == "REELS":
        return "reel"
    return FORMATS.get(media_type or "")


def thumbnail_of(item: dict[str, Any]) -> str | None:
    """A preview image. Photos and carousels have media_url; a video's media_url is the video
    file, so videos and Reels use thumbnail_url (when the API gives it)."""
    if item.get("thumbnail_url"):
        return item["thumbnail_url"]
    if item.get("media_type") != "VIDEO":
        return item.get("media_url")
    return None


def parse_media(item: dict[str, Any]) -> dict[str, Any]:
    """One media item (hashtag result or Business Discovery post) -> post fields."""
    return {
        "external_id": item["id"],
        "url": item["permalink"],
        "title": None,  # Instagram has only a caption, which goes in `text`
        "text": item.get("caption") or None,
        "published_at": parse_datetime(item.get("timestamp")),
        "format": media_format(item.get("media_type"), item.get("media_product_type")),
        "thumbnail_url": thumbnail_of(item),  # expires in about 4 days; renewed by every collect
        # Unknown stays None: a hidden like count is missing from the response.
        "views": to_int(item.get("view_count")),  # only Reels, only through Business Discovery
        "likes": to_int(item.get("like_count")),
        "comments": to_int(item.get("comments_count")),
        "shares": None,
    }
