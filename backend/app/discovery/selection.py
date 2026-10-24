"""Pure helpers that pick which competitors become active."""

import math


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
