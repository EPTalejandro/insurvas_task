"""Linking a competitor's YouTube channel to its own Instagram account.

Strict on purpose: no fuzzy name matching. YouTube does not give us a channel's social links, so
the only evidence is instagram.com links in the channel's video descriptions. That evidence is
noisy (guests and partners get linked too, and two channels of one team can share a handle), so
a handle is used only when it clearly belongs to this channel. Pure functions, no database.
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

_INSTAGRAM_URL = re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{1,30})", re.I)
# instagram.com/<word> addresses that are pages of Instagram, not accounts.
NOT_ACCOUNTS = {
    "p", "reel", "reels", "explore", "accounts", "stories", "tv", "direct", "about", "web",
    "legal", "developer", "share", "directory", "privacy", "help",
}  # fmt: skip

MIN_MENTIONS = 2  # a handle seen in one video is more likely a guest than the channel itself
DOMINANCE = 2.0  # with several handles, the top one must be mentioned this many times more


@dataclass(frozen=True)
class Candidate:
    handle: str
    mentions: int  # in how many descriptions it appears


@dataclass(frozen=True)
class LinkDecision:
    handle: str | None  # None: do not link
    reason: str
    confirmed: bool = False  # the Instagram profile links back to the channel


def extract_handles(text: str | None) -> set[str]:
    """Instagram account handles linked in a text, lowercase."""
    handles = set()
    for raw in _INSTAGRAM_URL.findall(text or ""):
        handle = raw.lower().rstrip(".")
        if handle and handle not in NOT_ACCOUNTS:
            handles.add(handle)
    return handles


def candidates_from(texts: Iterable[str | None]) -> list[Candidate]:
    """Handles linked in at least MIN_MENTIONS descriptions, most mentioned first."""
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update(extract_handles(text))  # a set, so one description counts once
    found = [Candidate(handle, n) for handle, n in counts.items() if n >= MIN_MENTIONS]
    return sorted(found, key=lambda c: (-c.mentions, c.handle))


def points_back(
    instagram_bio: str | None,
    instagram_website: str | None,
    youtube_handle: str | None,
    youtube_id: str,
) -> bool:
    """Does the Instagram profile link to this YouTube channel? The strongest proof we can get."""
    text = f"{instagram_bio or ''} {instagram_website or ''}".lower()
    parts = [rf"youtube\.com/channel/{re.escape(youtube_id.lower())}(?![a-z0-9_-])"]
    if youtube_handle and youtube_handle.startswith("@"):
        parts.append(rf"youtube\.com/{re.escape(youtube_handle.lower())}(?![a-z0-9._-])")
    return any(re.search(part, text) for part in parts)


def choose_handle(candidates: list[Candidate], confirmed: set[str]) -> LinkDecision:
    """Pick the channel's own Instagram handle, or say why there is none."""
    proven = [c for c in candidates if c.handle in confirmed]
    if len(proven) == 1:
        return LinkDecision(
            proven[0].handle, "the Instagram profile links back to the channel", True
        )
    if len(proven) > 1:
        return LinkDecision(None, "several Instagram profiles link back to the channel")
    if not candidates:
        return LinkDecision(None, f"no Instagram link in at least {MIN_MENTIONS} descriptions")

    top = candidates[0]
    if len(candidates) == 1:
        return LinkDecision(top.handle, f"linked in {top.mentions} descriptions")
    if top.mentions >= DOMINANCE * candidates[1].mentions:
        return LinkDecision(
            top.handle, f"linked in {top.mentions} descriptions, clearly the main one"
        )
    return LinkDecision(None, "several Instagram accounts and none clearly the channel's own")


def resolve_conflicts(decisions: dict[int, LinkDecision]) -> dict[int, LinkDecision]:
    """One Instagram account belongs to one competitor.

    If several competitors picked the same handle, only the one the profile links back to keeps
    it. When nobody can prove it, nobody gets it.
    """
    owners: dict[str, list[int]] = {}
    for competitor_id, decision in decisions.items():
        if decision.handle:
            owners.setdefault(decision.handle, []).append(competitor_id)

    resolved = dict(decisions)
    for handle, ids in owners.items():
        if len(ids) < 2:
            continue
        proven = [i for i in ids if decisions[i].confirmed]
        for competitor_id in ids:
            if proven == [competitor_id]:
                continue
            resolved[competitor_id] = LinkDecision(
                None, f"@{handle} is claimed by several competitors"
            )
    return resolved
