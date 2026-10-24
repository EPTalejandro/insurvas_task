"""The steps in order: [discover] -> collect -> label -> rank. Used by `refresh`."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.collectors.instagram import collect_hashtags, instagram_enabled
from app.collectors.youtube import collect_youtube
from app.config import Settings
from app.discovery.discover import discover_youtube
from app.discovery.location import update_locations, update_post_locations
from app.httpclient import make_client
from app.labeling.service import RULES, Labeler, label_posts
from app.models import Run
from app.ranking.service import rank_all

# Instagram hashtag pages take 12-26 seconds each, so the default 20 s timeout is too short.
INSTAGRAM_TIMEOUT = 90.0


@dataclass
class CollectResult:
    runs: list[Run] = field(default_factory=list)
    creator_locations: Counter[str] = field(default_factory=Counter)  # YouTube accounts
    post_locations: Counter[str] = field(default_factory=Counter)  # hashtag posts


def pick_labeler(settings: Settings) -> Labeler:
    """Rules for now. Phase 7 returns the Gemini labeler when a key is set."""
    return RULES


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
) -> CollectResult:
    """Collect posts, then check locations: of YouTube accounts and of hashtag captions."""
    platforms = enabled_platforms(settings) if platforms is None else platforms
    result = CollectResult()
    if "youtube" in platforms:
        result.runs.append(collect_youtube(session, client, settings, now))
        result.creator_locations = update_locations(session)
    if "instagram" in platforms:
        if instagram_client is None:
            with make_client(INSTAGRAM_TIMEOUT) as own_client:
                result.runs.append(collect_hashtags(session, own_client, settings, now))
        else:
            result.runs.append(collect_hashtags(session, instagram_client, settings, now))
        result.post_locations = update_post_locations(session)
    return result


def refresh(
    session: Session,
    client: httpx.Client,
    settings: Settings,
    *,
    discover: bool = False,
    now: datetime | None = None,
    instagram_client: httpx.Client | None = None,
) -> list[Run]:
    """Run every step. Platforms without keys are skipped, label and rank still run."""
    done: list[Run] = []
    if discover and settings.youtube_api_key:
        done.append(discover_youtube(session, client, settings, now))
    done += collect_step(session, client, settings, now, instagram_client=instagram_client).runs
    done.append(label_posts(session, pick_labeler(settings)))
    done.append(rank_all(session, now))
    return done
