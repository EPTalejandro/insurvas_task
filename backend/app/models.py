from datetime import UTC, datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

HASHTAG_KIND = "hashtag"  # Creator.kind of the placeholder that owns a hashtag's posts


def utcnow() -> datetime:
    return datetime.now(UTC)


class Competitor(Base):
    """A real life insurance agent or agency we track."""

    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    kind: Mapped[str]  # agent | agency
    website: Mapped[str | None]
    # Only "active" competitors are collected and ranked. "candidate" waits for review.
    status: Mapped[str] = mapped_column(index=True)  # active | candidate | excluded
    discovery_score: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    creators: Mapped[list["Creator"]] = relationship(back_populates="competitor")


class Creator(Base):
    """One account on one platform. competitor_id stays empty until the account is linked."""

    __tablename__ = "creators"
    __table_args__ = (UniqueConstraint("platform", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    competitor_id: Mapped[int | None] = mapped_column(ForeignKey("competitors.id"), index=True)
    platform: Mapped[str] = mapped_column(index=True)  # youtube | instagram
    external_id: Mapped[str]  # YouTube channel id / IG user id
    handle: Mapped[str]
    name: Mapped[str]
    url: Mapped[str | None]
    bio: Mapped[str | None]
    followers: Mapped[int | None]  # None when the platform does not expose it
    kind: Mapped[str | None]  # agent | agency | HASHTAG_KIND
    is_relevant: Mapped[bool] = mapped_column(default=True)
    discovered_via: Mapped[str | None]  # the keyword or link that found this account
    # Where the owner says they are (ISO code such as "US"). Often left empty on YouTube.
    country: Mapped[str | None]
    # us = country is US | likely_us = strong text signals | unverified | non_us
    location_status: Mapped[str] = mapped_column(default="unverified", index=True)
    # The proof behind the status, so a person can check it (e.g. "NPN mentioned").
    location_evidence: Mapped[str | None]

    competitor: Mapped[Competitor | None] = relationship(back_populates="creators")
    posts: Mapped[list["Post"]] = relationship(back_populates="creator")


class Post(Base):
    """One piece of public content with the latest metrics we collected."""

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
    # short_video | long_video | reel | video | image | carousel | text | link
    format: Mapped[str | None] = mapped_column(index=True)
    thumbnail_url: Mapped[str | None]

    # None means "the platform does not give us this". Never store unknown as 0.
    views: Mapped[int | None]
    likes: Mapped[int | None]
    comments: Mapped[int | None]
    shares: Mapped[int | None]

    last_collected_at: Mapped[datetime] = mapped_column(default=utcnow)

    # Only set for posts whose author is unknown (hashtag results): we judge the caption instead.
    location_status: Mapped[str | None]  # likely_us | probable_us | unverified | non_us
    location_evidence: Mapped[str | None]

    creator: Mapped[Creator] = relationship(back_populates="posts")
    label: Mapped["Label | None"] = relationship(
        back_populates="post", cascade="all, delete-orphan", uselist=False
    )
    scores: Mapped[list["PostScore"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


class Label(Base):
    """Topic, hook and CTA labels for one post."""

    __tablename__ = "labels"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    topic: Mapped[str | None] = mapped_column(index=True)
    hook_type: Mapped[str | None] = mapped_column(index=True)
    hook_text: Mapped[str | None]
    cta: Mapped[str | None]
    is_relevant: Mapped[bool] = mapped_column(default=True)
    # Shows off results (income, records, awards) with nothing to learn: labeled, never ranked.
    is_flex: Mapped[bool] = mapped_column(default=False)
    confidence: Mapped[float | None]
    labeler: Mapped[str]  # rules | gemini
    model: Mapped[str | None]  # resolved Gemini model, e.g. gemini-3.5-flash-lite
    # Lets us skip re-labeling unchanged posts and re-label when the taxonomy changes.
    content_hash: Mapped[str | None]
    taxonomy_version: Mapped[int]
    labeled_at: Mapped[datetime] = mapped_column(default=utcnow)

    post: Mapped[Post] = relationship(back_populates="label")


class PostScore(Base):
    """A post's score inside one time window (1, 7, 30 or 90 days)."""

    __tablename__ = "post_scores"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    window_days: Mapped[int] = mapped_column(primary_key=True)
    adjusted_engagement: Mapped[float | None]
    engagement_rate: Mapped[float | None]
    outperformance: Mapped[float | None]
    score: Mapped[float | None] = mapped_column(index=True)  # 0-100
    rank_in_platform: Mapped[int | None]
    reason: Mapped[str | None]

    post: Mapped[Post] = relationship(back_populates="scores")


class CompetitorScore(Base):
    """A competitor's score inside one time window."""

    __tablename__ = "competitor_scores"

    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), primary_key=True)
    window_days: Mapped[int] = mapped_column(primary_key=True)
    score: Mapped[float | None] = mapped_column(index=True)
    posts_count: Mapped[int]
    consistency: Mapped[float | None]
    best_post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"))
    top_topic: Mapped[str | None]
    top_hook: Mapped[str | None]
    # True when there are too few posts to trust the score. The UI hides these by default.
    low_sample: Mapped[bool] = mapped_column(default=False)


class Keyword(Base):
    """A search term used by discovery. platform=None means all platforms."""

    __tablename__ = "keywords"
    __table_args__ = (UniqueConstraint("term", "platform"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str]
    platform: Mapped[str | None]
    active: Mapped[bool] = mapped_column(default=True)


class Run(Base):
    """Log of one pipeline step, shown in the Sources tab."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]  # discover | collect | label | rank
    platform: Mapped[str | None]
    status: Mapped[str]  # running | ok | partial | error
    items_ok: Mapped[int] = mapped_column(default=0)
    items_failed: Mapped[int] = mapped_column(default=0)
    quota_used: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None]
    # Hashtags this run searched, comma-separated. Instagram allows 30 different hashtags per
    # 7 days, and this is how the Sources tab knows how many are left.
    hashtags: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]
