"""Pure helpers that pick which competitors become active, and which ones stop being active."""

import math
from datetime import datetime

from app.ranking.scoring import as_utc

# An active competitor with no ranked post in this ranking window makes room for a new one.
STALE_WINDOW = 30


def discovery_score(followers: int | None, platforms: int) -> float:
    """Bigger audiences score higher; being on more platforms adds a small bonus."""
    return math.log10(1 + (followers or 0)) + 0.5 * (platforms - 1)


def choose_new_active(candidates: list[tuple[int, float]], slots: int) -> list[int]:
    """Pick the best-scoring candidate ids to fill the free slots.

    candidates are (competitor_id, discovery_score). Ties go to the lower id so reruns
    give the same list.
    """
    ranked = sorted(candidates, key=lambda c: (-c[1], c[0]))
    return [competitor_id for competitor_id, _ in ranked[: max(slots, 0)]]


def stale_competitors(
    active: list[tuple[int, datetime | None]],
    with_ranked_posts: set[int],
    judged_since: datetime | None,
) -> list[int]:
    """Active ids with no ranked post in the last STALE_WINDOW days, among those already judged.

    active is (competitor_id, activated_at). judged_since is when the posts behind the latest
    scores were collected: a competitor activated after it has not been collected and ranked
    yet, so it is too early to say. Collecting reads 90 days back, so one collect and rank is
    enough to judge the last 30 days; there is no need to wait 30 calendar days.
    """
    if judged_since is None:
        return []
    return [
        competitor_id
        for competitor_id, activated_at in active
        if activated_at is not None
        and as_utc(activated_at) <= as_utc(judged_since)
        and competitor_id not in with_ranked_posts
    ]
