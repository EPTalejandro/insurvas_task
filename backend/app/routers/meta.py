from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api_common import PLATFORMS, utc
from app.config import Settings, get_settings
from app.db import get_session
from app.labeling.taxonomy import CTAS, FORMAT_GROUPS, HOOKS, TAXONOMY_VERSION, TOPICS
from app.models import Competitor, Label, Post, PostScore, Run
from app.pipeline import enabled_platforms
from app.ranking import config
from app.schemas import (
    CountsOut,
    MetaOut,
    Option,
    PlatformOut,
    TaxonomyOut,
    ThresholdsOut,
)

router = APIRouter()


def _options(names: dict[str, str]) -> list[Option]:
    return [Option(id=key, label=text) for key, text in names.items()]


@router.get("/meta", response_model=MetaOut)
def get_meta(
    session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> MetaOut:
    """Everything the UI needs to build its pickers and badges."""
    counts = session.execute(select(Post.platform, func.count()).group_by(Post.platform)).all()
    posts_by_platform = dict(counts)
    enabled = enabled_platforms(settings)
    last_ranked = session.scalar(
        select(func.max(Run.finished_at)).where(Run.kind == "rank", Run.status == "ok")
    )
    return MetaOut(
        windows=list(config.WINDOWS),
        default_window=config.DEFAULT_WINDOW,
        platforms=[
            PlatformOut(
                id=platform,
                label=label,
                enabled=platform in enabled,
                posts=posts_by_platform.get(platform, 0),
            )
            for platform, label in PLATFORMS.items()
        ],
        taxonomy=TaxonomyOut(
            version=TAXONOMY_VERSION,
            topics=_options(TOPICS),
            hooks=_options(HOOKS),
            ctas=_options(CTAS),
            formats=_options({key: text for key, (text, _) in FORMAT_GROUPS.items()}),
        ),
        thresholds=ThresholdsOut(
            strong_score=config.STRONG_SCORE,
            good_score=config.GOOD_SCORE,
            min_group_size=config.MIN_GROUP_SIZE,
            min_engagement_to_rank=config.MIN_ENGAGEMENT_TO_RANK,
            min_post_age_hours=config.MIN_POST_AGE_HOURS,
            min_posts_by_window=config.MIN_POSTS_BY_WINDOW,
        ),
        last_updated=utc(last_ranked),
        counts=CountsOut(
            competitors=session.scalar(
                select(func.count()).select_from(Competitor).where(Competitor.status == "active")
            ),
            posts=sum(posts_by_platform.values()),
            labeled_posts=session.scalar(select(func.count()).select_from(Label)),
            ranked_posts=session.scalar(
                select(func.count())
                .select_from(PostScore)
                .where(PostScore.window_days == config.DEFAULT_WINDOW)
            ),
        ),
    )
