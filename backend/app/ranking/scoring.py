"""Post and competitor scoring. Pure functions: no database, no clock (`now` is a parameter)."""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from app.ranking import config

PLATFORM_NAMES = {"youtube": "YouTube", "instagram": "Instagram"}


@dataclass(frozen=True)
class PostInput:
    post_id: int
    creator_id: int
    platform: str
    published_at: datetime  # timezone-aware, UTC
    likes: int | None
    comments: int | None
    shares: int | None
    views: int | None
    followers: int | None
    # False when the competitor is not active or the creator or label says "not relevant".
    counts: bool
    # False for hashtag posts: the "creator" is a placeholder, so there is no usual to compare to.
    known_author: bool = True


@dataclass(frozen=True)
class PostResult:
    post_id: int
    engagements: float  # likes + comments + shares, before the age adjustment
    adjusted_engagement: float
    engagement_rate: float | None
    outperformance: float | None
    score: float  # 0-100
    rank_in_platform: int
    reason: str


@dataclass(frozen=True)
class ScoredPost:
    """What the competitor score needs to know about one scored post."""

    post_id: int
    score: float
    topic: str | None
    hook_type: str | None


@dataclass(frozen=True)
class CompetitorResult:
    score: float
    posts_count: int
    consistency: float
    best_post_id: int
    top_topic: str | None
    top_hook: str | None
    low_sample: bool


def as_utc(value: datetime) -> datetime:
    """SQLite gives back naive datetimes; everything we store is UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def age_days(published_at: datetime, now: datetime) -> float:
    return (now - published_at).total_seconds() / 86400


def engagements(likes: int | None, comments: int | None, shares: int | None) -> float:
    """Weighted sum of the metrics we know. Unknown (None) metrics are skipped, not zero."""
    metrics = {"likes": likes, "comments": comments, "shares": shares}
    return sum(config.ENGAGEMENT_WEIGHTS[name] * value for name, value in metrics.items() if value)


def adjusted_engagement(total: float, age: float) -> float:
    """Divide by a slowly growing number so old posts do not win just by being old."""
    return total / math.log2(2 + age)


def percentile_rank(value: float, values: list[float]) -> float:
    """Share of values below this one (ties count half), 0-100. One value gives 50."""
    less = sum(1 for other in values if other < value)
    equal = sum(1 for other in values if other == value)
    return 100 * (less + 0.5 * equal) / len(values)


def is_eligible(
    post: PostInput, window_days: int, now: datetime, min_engagement: float = 0
) -> bool:
    """Counted, old enough for its numbers to settle, has data, and enough engagement."""
    age = age_days(post.published_at, now)
    has_data = post.likes is not None or post.comments is not None
    enough = engagements(post.likes, post.comments, post.shares) >= min_engagement
    return (
        post.counts and has_data and enough and config.MIN_POST_AGE_HOURS / 24 <= age <= window_days
    )


def make_reason(platform: str, total: float, outperformance: float | None, score: float) -> str:
    """Lead with the absolute numbers, then say why it stands out."""
    noun = "engagement" if round(total) == 1 else "engagements"
    base = f"{total:,.0f} {noun}"
    if outperformance is not None and outperformance >= config.OUTPERFORM_REASON_MIN:
        return f"{base} · {outperformance:.1f}× this creator's usual"
    top = max(1, round(100 - score))
    return f"{base} · top {top}% on {PLATFORM_NAMES.get(platform, platform)}"


def _creator_baselines(posts: list[PostInput], now: datetime) -> dict[int, float | None]:
    """Median adjusted engagement per creator over 90 days. Quiet posts count too."""
    by_creator: dict[int, list[float]] = defaultdict(list)
    for post in posts:
        if post.known_author and is_eligible(post, config.BASELINE_DAYS, now):
            total = engagements(post.likes, post.comments, post.shares)
            by_creator[post.creator_id].append(
                adjusted_engagement(total, age_days(post.published_at, now))
            )
    return {
        creator: median(values) if len(values) >= config.MIN_BASELINE_POSTS else None
        for creator, values in by_creator.items()
    }


@dataclass(frozen=True)
class _Measured:
    post: PostInput
    total: float
    adjusted: float
    rate: float | None  # engagement per follower: shown to the user, not part of the score
    outperformance: float | None
    reach: float | None  # age-adjusted views


def _blend(parts: list[tuple[float, float]], fallback: float) -> float:
    """Weighted mean of (weight, percentile). Missing parts are left out, not counted as 0."""
    total_weight = sum(weight for weight, _ in parts)
    if total_weight == 0:
        return fallback
    return sum(weight * value for weight, value in parts) / total_weight


def _measure(posts: list[PostInput], window_days: int, now: datetime) -> list[_Measured]:
    """Numbers for every ranked post of the window, before any percentile."""
    baselines = _creator_baselines(posts, now)
    measured = []
    for post in posts:
        if not is_eligible(post, window_days, now, config.MIN_ENGAGEMENT_TO_RANK):
            continue
        age = age_days(post.published_at, now)
        total = engagements(post.likes, post.comments, post.shares)
        adjusted = adjusted_engagement(total, age)
        rate = adjusted / post.followers if post.followers else None
        baseline = baselines.get(post.creator_id)
        # The floor stops a creator with almost no engagement from showing a huge multiple.
        outperformance = (
            adjusted / max(baseline, config.BASELINE_FLOOR) if baseline is not None else None
        )
        reach = adjusted_engagement(post.views, age) if post.views is not None else None
        measured.append(_Measured(post, total, adjusted, rate, outperformance, reach))
    return measured


def _score_platform(platform: str, items: list[_Measured]) -> list[PostResult]:
    """Percentiles inside one platform, so YouTube and Instagram are not compared directly."""
    adjusteds = [i.adjusted for i in items]
    outperformances = [i.outperformance for i in items if i.outperformance is not None]
    reaches = [i.reach for i in items if i.reach is not None]

    scored: list[tuple[float, _Measured]] = []
    for item in items:
        impact = percentile_rank(item.adjusted, adjusteds)
        parts = [(config.BLEND["impact"], impact)]
        if item.outperformance is not None:
            percentile = percentile_rank(item.outperformance, outperformances)
            parts.append((config.BLEND["outperformance"], percentile))
        if item.reach is not None:
            parts.append((config.BLEND["reach"], percentile_rank(item.reach, reaches)))
        scored.append((_blend(parts, fallback=impact), item))

    # Best first; ties go to more engagement, then the lower id, so reruns match.
    scored.sort(key=lambda s: (-s[0], -s[1].adjusted, s[1].post.post_id))
    return [
        PostResult(
            post_id=item.post.post_id,
            engagements=item.total,
            adjusted_engagement=item.adjusted,
            engagement_rate=item.rate,
            outperformance=item.outperformance,
            score=score,
            rank_in_platform=position,
            reason=make_reason(platform, item.total, item.outperformance, score),
        )
        for position, (score, item) in enumerate(scored, start=1)
    ]


def score_posts(posts: list[PostInput], window_days: int, now: datetime) -> list[PostResult]:
    """Score every eligible post of one window."""
    by_platform: dict[str, list[_Measured]] = defaultdict(list)
    for item in _measure(posts, window_days, now):
        by_platform[item.post.platform].append(item)
    results: list[PostResult] = []
    for platform, items in by_platform.items():
        results += _score_platform(platform, items)
    return results


def _top_label(posts: list[ScoredPost], field: str, ignore: str) -> str | None:
    """Most used label among a competitor's posts; ties go to the higher average score."""
    scores: dict[str, list[float]] = defaultdict(list)
    for post in posts:
        value = getattr(post, field)
        if value and value != ignore:
            scores[value].append(post.score)
    if not scores:
        return None
    counts = Counter({value: len(values) for value, values in scores.items()})
    best = max(counts.values())
    tied = [value for value, count in counts.items() if count == best]
    return max(sorted(tied), key=lambda value: sum(scores[value]) / len(scores[value]))


def score_competitor(posts: list[ScoredPost], window_days: int) -> CompetitorResult | None:
    """Median post score, discounted when only a few posts are good."""
    if not posts:
        return None
    post_scores = [post.score for post in posts]
    consistency = sum(1 for s in post_scores if s >= config.CONSISTENT_SCORE) / len(post_scores)
    best = max(posts, key=lambda p: (p.score, -p.post_id))
    return CompetitorResult(
        score=median(post_scores) * (0.5 + 0.5 * consistency),
        posts_count=len(posts),
        consistency=consistency,
        best_post_id=best.post_id,
        top_topic=_top_label(posts, "topic", ignore="other"),
        top_hook=_top_label(posts, "hook_type", ignore="none"),
        low_sample=len(posts) < config.MIN_POSTS_BY_WINDOW[window_days],
    )
