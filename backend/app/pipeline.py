"""The steps in order: [discover] -> collect -> label -> rank. Used by `refresh`."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.collectors.instagram import collect_hashtags, instagram_enabled
from app.collectors.instagram_accounts import collect_instagram_accounts, link_instagram_accounts
from app.collectors.youtube import collect_youtube
from app.config import Settings
from app.discovery.discover import discover_youtube
from app.discovery.gemini_review import GeminiReviewer
from app.discovery.location import update_locations, update_post_locations
from app.gemini_client import GeminiJson, make_gemini
from app.httpclient import make_client
from app.labeling.gemini import GeminiLabeler
from app.labeling.service import RULES, Labeler, label_posts
from app.models import Run
from app.ranking.service import rank_all

# Instagram hashtag pages take 12-26 seconds each, so the default 20 s timeout is too short.
INSTAGRAM_TIMEOUT = 90.0


@dataclass
class CollectResult:
    runs: list[Run] = field(default_factory=list)
    creator_locations: Counter[str] = field(default_factory=Counter)  # competitors' accounts
    post_locations: Counter[str] = field(default_factory=Counter)  # hashtag posts


def pick_labeler(settings: Settings, gemini: GeminiJson | None = None) -> Labeler:
    """Gemini when there is a key (and LABELER is not "rules"), otherwise the rules."""
    gemini = gemini or make_gemini(settings)
    if gemini is None:
        return RULES
    return GeminiLabeler(gemini).as_labeler()


def pick_reviewer(settings: Settings, gemini: GeminiJson | None = None) -> GeminiReviewer | None:
    """Gemini's second opinion on accounts, under the same conditions as the labeler."""
    gemini = gemini or make_gemini(settings)
    return GeminiReviewer(gemini) if gemini else None


def enabled_platforms(settings: Settings) -> list[str]:
    """A platform is on when its keys are set."""
    platforms = []
    if settings.youtube_api_key:
        platforms.append("youtube")
    if instagram_enabled(settings):
        platforms.append("instagram")
    return platforms


def collect_step(
    session: Session,
    client: httpx.Client,
    settings: Settings,
    now: datetime | None = None,
    platforms: list[str] | None = None,
    instagram_client: httpx.Client | None = None,
    reviewer: GeminiReviewer | None = None,
) -> CollectResult:
    """Collect posts, then check where the accounts and hashtag posts are based."""
    platforms = enabled_platforms(settings) if platforms is None else platforms
    result = CollectResult()
    if "youtube" in platforms:
        result.runs.append(collect_youtube(session, client, settings, now))
    if "instagram" in platforms:
        if instagram_client is None:
            with make_client(INSTAGRAM_TIMEOUT) as own_client:
                result.runs += _collect_instagram(session, own_client, settings, now)
        else:
            result.runs += _collect_instagram(session, instagram_client, settings, now)
        result.post_locations = update_post_locations(session)
    if platforms:
        # After both platforms: an Instagram account can lean on its YouTube channel's status.
        result.creator_locations = update_locations(session, reviewer)
    return result


def _collect_instagram(
    session: Session, client: httpx.Client, settings: Settings, now: datetime | None
) -> list[Run]:
    """Link competitors to their Instagram accounts, collect those, then the hashtag posts."""
    return [
        link_instagram_accounts(session, client, settings),
        collect_instagram_accounts(session, client, settings, now),
        collect_hashtags(session, client, settings, now),
    ]


def refresh(
    session: Session,
    client: httpx.Client,
    settings: Settings,
    *,
    discover: bool = False,
    now: datetime | None = None,
    instagram_client: httpx.Client | None = None,
    gemini: GeminiJson | None = None,
) -> list[Run]:
    """Run every step. Platforms without keys are skipped, label and rank still run."""
    # One connection for everything, so the requests-per-minute limit holds across all of it.
    gemini = gemini or make_gemini(settings)
    reviewer = GeminiReviewer(gemini) if gemini else None
    done: list[Run] = []
    if discover and settings.youtube_api_key:
        done.append(discover_youtube(session, client, settings, now, reviewer))
    collected = collect_step(
        session, client, settings, now, instagram_client=instagram_client, reviewer=reviewer
    )
    done += collected.runs
    done.append(label_posts(session, pick_labeler(settings, gemini)))
    done.append(rank_all(session, now))
    return done
