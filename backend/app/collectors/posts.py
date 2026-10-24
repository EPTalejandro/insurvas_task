"""Saving collected posts: shared by every platform's collector."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Creator, Post


def upsert_posts(
    session: Session,
    creator: Creator,
    parsed: list[dict[str, Any]],
    now: datetime,
    platform: str,
) -> int:
    """Insert new posts and refresh metrics of known ones. Returns how many were written."""
    ids = [post["external_id"] for post in parsed]
    existing = {
        post.external_id: post
        for post in session.scalars(
            select(Post).where(Post.platform == platform, Post.external_id.in_(ids))
        )
    }
    for item in parsed:
        fields = {k: v for k, v in item.items() if k != "channel_id"}
        post = existing.get(item["external_id"])
        if post is None:
            post = Post(creator_id=creator.id, platform=platform, **fields)
            session.add(post)
        else:
            for name, value in fields.items():
                setattr(post, name, value)
        post.last_collected_at = now
    session.commit()
    return len(parsed)
