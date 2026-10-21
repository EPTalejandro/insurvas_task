from datetime import UTC, datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Creator(Base):
    """An agent or agency account on one platform."""

    __tablename__ = "creators"
    __table_args__ = (UniqueConstraint("platform", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(index=True)  # youtube | instagram | threads
    external_id: Mapped[str]  # YouTube channel id / IG user id / Threads user id
    handle: Mapped[str]
    name: Mapped[str]
    url: Mapped[str | None]
    followers: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    posts: Mapped[list["Post"]] = relationship(back_populates="creator")


class Post(Base):
    """One piece of public content with a snapshot of its metrics."""

    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("platform", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), index=True)
    platform: Mapped[str] = mapped_column(index=True)
    external_id: Mapped[str]
    url: Mapped[str]
    title: Mapped[str | None]
    text: Mapped[str | None]
    published_at: Mapped[datetime | None] = mapped_column(index=True)
    format: Mapped[str | None] = mapped_column(index=True)  # short_video | long_video | image ...
    duration_s: Mapped[int | None]

    # Metrics. Nullable because not every platform exposes every number.
    views: Mapped[int | None]
    likes: Mapped[int | None]
    comments: Mapped[int | None]
    shares: Mapped[int | None]

    source: Mapped[str]  # youtube_api | instagram_api | threads_api
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)

    # Filled in by the ranking step.
    engagement_rate: Mapped[float | None]
    outperformance: Mapped[float | None]
    score: Mapped[float | None] = mapped_column(index=True)
    scored_at: Mapped[datetime | None]

    creator: Mapped[Creator] = relationship(back_populates="posts")
    label: Mapped["Label | None"] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class Label(Base):
    """Topic / hook / CTA labels for a post (one row per post)."""

    __tablename__ = "labels"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    topic: Mapped[str | None] = mapped_column(index=True)
    hook_type: Mapped[str | None] = mapped_column(index=True)
    hook_text: Mapped[str | None]
    cta: Mapped[str | None]
    confidence: Mapped[float | None]
    labeler: Mapped[str]  # rules | gemini | human
    model: Mapped[str | None]  # e.g. gemini-2.5-flash
    content_hash: Mapped[str | None]  # skip re-labeling unchanged posts
    labeled_at: Mapped[datetime] = mapped_column(default=utcnow)

    post: Mapped[Post] = relationship(back_populates="label")
