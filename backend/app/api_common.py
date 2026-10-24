"""Shared pieces of the API: parameter checks, the ranked-posts query and row converters."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException, Query
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.labeling.taxonomy import FORMATS, HOOKS, TOPICS
from app.models import HASHTAG_KIND, Competitor, Creator, Label, Post, PostScore
from app.ranking import config
from app.ranking.scoring import as_utc
from app.schemas import (
    AccountOut,
    LabelOut,
    LocationOut,
    MetricsOut,
    PostCreatorOut,
    PostOut,
    ScoreOut,
)

PLATFORMS = {"youtube": "YouTube", "instagram": "Instagram"}
TEXT_PREVIEW_CHARS = 280


# --- parameter checks (a wrong value is a 422, like any other bad input) -----------------------


def choice(value: str | None, allowed: Iterable[str], name: str) -> str | None:
    allowed = list(allowed)
    if value is not None and value not in allowed:
        raise HTTPException(status_code=422, detail=f"{name} must be one of: {', '.join(allowed)}")
    return value


def window_param(window: int = Query(config.DEFAULT_WINDOW)) -> int:
    if window not in config.WINDOWS:
        allowed = ", ".join(str(w) for w in config.WINDOWS)
        raise HTTPException(status_code=422, detail=f"window must be one of: {allowed}")
    return window


@dataclass(frozen=True)
class PostFilters:
    platform: str | None = None
    topic: str | None = None
    hook_type: str | None = None
    format: str | None = None
    competitor_id: int | None = None


def post_filters(
    platform: str | None = Query(None),
    topic: str | None = Query(None),
    hook_type: str | None = Query(None),
    format: str | None = Query(None),
    competitor_id: int | None = Query(None),
) -> PostFilters:
    return PostFilters(
        platform=choice(platform, PLATFORMS, "platform"),
        topic=choice(topic, TOPICS, "topic"),
        hook_type=choice(hook_type, HOOKS, "hook_type"),
        format=choice(format, FORMATS, "format"),
        competitor_id=competitor_id,
    )


# --- queries -----------------------------------------------------------------------------------


def join_ranked(stmt: Select, window: int) -> Select:
    """Posts that have a score in this window, with their creator and label."""
    return (
        stmt.select_from(Post)
        .join(PostScore, and_(PostScore.post_id == Post.id, PostScore.window_days == window))
        .join(Creator, Creator.id == Post.creator_id)
        .outerjoin(Label, Label.post_id == Post.id)
    )


def apply_filters(stmt: Select, filters: PostFilters) -> Select:
    if filters.platform:
        stmt = stmt.where(Post.platform == filters.platform)
    if filters.topic:
        stmt = stmt.where(Label.topic == filters.topic)
    if filters.hook_type:
        stmt = stmt.where(Label.hook_type == filters.hook_type)
    if filters.format:
        stmt = stmt.where(Post.format == filters.format)
    if filters.competitor_id is not None:
        stmt = stmt.where(Creator.competitor_id == filters.competitor_id)
    return stmt


def ranked_posts_stmt(window: int, filters: PostFilters) -> Select:
    stmt = select(Post, Creator, Label, PostScore)
    return apply_filters(join_ranked(stmt, window), filters).order_by(
        PostScore.score.desc(), PostScore.adjusted_engagement.desc(), Post.id
    )


def ranked_count_stmt(window: int, filters: PostFilters) -> Select:
    return apply_filters(join_ranked(select(func.count(Post.id)), window), filters)


def too_new_count(session: Session, filters: PostFilters, now: datetime) -> int:
    """Posts that would be ranked but are under 6 hours old, so their numbers are not settled."""
    cutoff = (now - timedelta(hours=config.MIN_POST_AGE_HOURS)).replace(tzinfo=None)
    stmt = (
        select(func.count(Post.id))
        .select_from(Post)
        .join(Creator, Creator.id == Post.creator_id)
        .outerjoin(Competitor, Competitor.id == Creator.competitor_id)
        .outerjoin(Label, Label.post_id == Post.id)
        .where(Post.published_at > cutoff, Creator.is_relevant)
        .where(
            or_(
                and_(Creator.kind != HASHTAG_KIND, Competitor.status == "active"),
                and_(
                    Creator.kind == HASHTAG_KIND, Post.location_status.in_(config.HASHTAG_LOCATIONS)
                ),
            )
        )
    )
    return session.scalar(apply_filters(stmt, filters)) or 0


# --- converters --------------------------------------------------------------------------------


def utc(value: datetime | None) -> datetime | None:
    """SQLite gives back naive datetimes; they are UTC, and the API says so."""
    return as_utc(value) if value else None


def location_of(post: Post, creator: Creator) -> LocationOut:
    """Hashtag posts are judged by caption; everything else by the account."""
    if creator.kind == HASHTAG_KIND:
        return LocationOut(
            status=post.location_status or "unverified", evidence=post.location_evidence
        )
    return LocationOut(status=creator.location_status, evidence=creator.location_evidence)


def account_out(creator: Creator) -> AccountOut:
    return AccountOut(
        platform=creator.platform,
        handle=creator.handle,
        name=creator.name,
        url=creator.url,
        followers=creator.followers,
        location=LocationOut(status=creator.location_status, evidence=creator.location_evidence),
    )


def to_post_out(post: Post, creator: Creator, label: Label | None, score: PostScore) -> PostOut:
    text = post.text
    return PostOut(
        id=post.id,
        platform=post.platform,
        url=post.url,
        title=post.title,
        text_preview=text[:TEXT_PREVIEW_CHARS] if text else None,
        published_at=utc(post.published_at),
        format=post.format,
        thumbnail_url=post.thumbnail_url,
        creator=PostCreatorOut(
            id=creator.id,
            platform=creator.platform,
            name=creator.name,
            handle=creator.handle,
            followers=creator.followers,
            competitor_id=creator.competitor_id,
        ),
        metrics=MetricsOut(
            views=post.views, likes=post.likes, comments=post.comments, shares=post.shares
        ),
        label=None
        if label is None
        else LabelOut(
            topic=label.topic,
            hook_type=label.hook_type,
            hook_text=label.hook_text,
            cta=label.cta,
            confidence=label.confidence,
            labeler=label.labeler,
        ),
        score=ScoreOut(
            score=score.score,
            rank_in_platform=score.rank_in_platform,
            engagement_rate=score.engagement_rate,
            outperformance=score.outperformance,
            adjusted_engagement=score.adjusted_engagement,
            reason=score.reason,
        ),
        location=location_of(post, creator),
    )
