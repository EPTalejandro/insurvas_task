"""Instagram's hashtag budget: 30 different hashtags per rolling 7 days.

Searching the same hashtag again inside the window does not take another slot; a slot is free
again 7 days after that hashtag's last search. Pure functions: the searches come from the runs
table and `now` is a parameter.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.ranking.scoring import as_utc

INSTAGRAM_HASHTAG_LIMIT = 30
HASHTAG_WINDOW_DAYS = 7


@dataclass(frozen=True)
class HashtagBudget:
    limit: int
    used: int
    free: int
    next_free_at: datetime | None  # when the first slot frees, None when none is taken
    slots: dict[str, datetime]  # hashtag -> when its slot frees


def searches_from_runs(runs: Iterable[tuple[str | None, datetime]]) -> list[tuple[str, datetime]]:
    """(run.hashtags, run.started_at) rows -> one (hashtag, searched_at) pair per search."""
    return [
        (tag, as_utc(started_at))
        for hashtags, started_at in runs
        for tag in (hashtags or "").split(",")
        if tag
    ]


def hashtag_budget(searches: list[tuple[str, datetime]], now: datetime) -> HashtagBudget:
    """Which hashtags hold a slot now, and until when."""
    window = timedelta(days=HASHTAG_WINDOW_DAYS)
    slots: dict[str, datetime] = {}
    for tag, searched_at in searches:
        frees_at = as_utc(searched_at) + window
        if frees_at > now:
            slots[tag] = max(frees_at, slots.get(tag, frees_at))
    used = len(slots)
    return HashtagBudget(
        limit=INSTAGRAM_HASHTAG_LIMIT,
        used=used,
        free=max(INSTAGRAM_HASHTAG_LIMIT - used, 0),
        next_free_at=min(slots.values(), default=None),
        slots=slots,
    )
