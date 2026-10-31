"""Request and response models of the HTTP API. The frontend mirrors them in `src/types.ts`."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# --- shared pieces -------------------------------------------------------------------------


class Option(BaseModel):
    id: str
    label: str


class MetricsOut(BaseModel):
    # None means "the platform does not give us this number", which is not the same as 0.
    views: int | None
    likes: int | None
    comments: int | None
    shares: int | None


class LabelOut(BaseModel):
    topic: str | None
    hook_type: str | None
    hook_text: str | None
    cta: str | None
    confidence: float | None
    labeler: str


class ScoreOut(BaseModel):
    score: float  # 0-100
    rank_in_platform: int | None
    engagement_rate: float | None
    outperformance: float | None
    adjusted_engagement: float | None
    reason: str | None


class LocationOut(BaseModel):
    """Why we think the content is US-based: a status and the evidence behind it."""

    status: str
    evidence: str | None


class AccountOut(BaseModel):
    platform: str
    handle: str
    name: str
    url: str | None
    followers: int | None
    location: LocationOut


class PostCreatorOut(BaseModel):
    id: int
    platform: str
    name: str
    handle: str
    followers: int | None
    competitor_id: int | None  # None for hashtag posts: their author is unknown


class PostOut(BaseModel):
    id: int
    platform: str
    url: str
    title: str | None
    text_preview: str | None
    published_at: datetime | None
    format: str | None
    thumbnail_url: str | None
    creator: PostCreatorOut
    metrics: MetricsOut
    label: LabelOut | None
    score: ScoreOut
    location: LocationOut


# --- /api/posts ----------------------------------------------------------------------------


class PostsPage(BaseModel):
    window: int
    items: list[PostOut]
    total: int
    limit: int
    offset: int
    too_new: int  # posts under 6 hours old: not ranked yet


# --- /api/competitors ----------------------------------------------------------------------


class BestPostOut(BaseModel):
    id: int
    url: str
    title: str | None
    score: float | None


class CompetitorOut(BaseModel):
    id: int
    name: str
    kind: str
    website: str | None
    status: str
    rank: int | None
    score: float | None
    posts_count: int
    consistency: float | None
    low_sample: bool
    top_topic: str | None
    top_hook: str | None
    best_post: BestPostOut | None
    accounts: list[AccountOut]


class CompetitorsPage(BaseModel):
    window: int
    items: list[CompetitorOut]
    total: int
    hidden_low_sample: int  # competitors left out for having too few posts in this window


class WindowScoreOut(BaseModel):
    window: int
    score: float
    posts_count: int
    consistency: float | None
    low_sample: bool


class CompetitorDetail(BaseModel):
    window: int
    competitor: CompetitorOut
    scores_by_window: list[WindowScoreOut]
    top_posts: list[PostOut]


# --- /api/insights -------------------------------------------------------------------------


class InsightGroup(BaseModel):
    value: str
    label: str
    count: int
    avg_score: float
    avg_engagement: float


class InsightsOut(BaseModel):
    window: int
    group_by: str
    platform: str | None
    groups: list[InsightGroup]
    hidden_groups: int  # groups with fewer than `min_group_size` posts
    hidden_posts: int
    total_posts: int
    min_group_size: int


# --- /api/meta, /api/runs, /api/keywords ---------------------------------------------------


class PlatformOut(BaseModel):
    id: str
    label: str
    enabled: bool  # keys are set in .env
    posts: int


class TaxonomyOut(BaseModel):
    version: int
    topics: list[Option]
    hooks: list[Option]
    ctas: list[Option]
    formats: list[Option]


class ThresholdsOut(BaseModel):
    strong_score: int
    good_score: int
    min_group_size: int
    min_engagement_to_rank: int
    min_post_age_hours: int
    min_posts_by_window: dict[int, int]


class CountsOut(BaseModel):
    competitors: int
    posts: int
    labeled_posts: int
    ranked_posts: int  # in the default window
    flex_posts: int  # labeled as flex, so never ranked


class MetaOut(BaseModel):
    windows: list[int]
    default_window: int
    platforms: list[PlatformOut]
    taxonomy: TaxonomyOut
    thresholds: ThresholdsOut
    last_updated: datetime | None
    counts: CountsOut


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    platform: str | None
    status: str
    items_ok: int
    items_failed: int
    quota_used: int
    message: str | None
    started_at: datetime
    finished_at: datetime | None


class KeywordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    term: str
    platform: str | None
    active: bool


class KeywordIn(BaseModel):
    """A new search term (platform None) or hashtag (platform "instagram")."""

    term: str = Field(max_length=200)
    platform: str | None = None


class KeywordPatch(BaseModel):
    active: bool


class HashtagSlotOut(BaseModel):
    tag: str
    frees_at: datetime


class HashtagBudgetOut(BaseModel):
    """Instagram allows 30 different hashtags per 7 days; a repeated search takes no new slot."""

    limit: int
    used: int
    free: int
    next_free_at: datetime | None
    slots: list[HashtagSlotOut]  # soonest to free first
