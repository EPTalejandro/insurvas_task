from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api_common import PLATFORMS, choice, join_ranked, window_param
from app.db import get_session
from app.labeling.taxonomy import FORMAT_GROUPS, HOOKS, TOPICS
from app.models import Label, Post, PostScore
from app.ranking import config
from app.schemas import InsightGroup, InsightsOut

router = APIRouter()

# Formats are grouped like the filter: a Reel counts as a short video, a carousel as images.
FORMAT_GROUP_COLUMN = case(
    *[(Post.format.in_(formats), key) for key, (_, formats) in FORMAT_GROUPS.items()],
    else_=None,
)

# group_by value -> (column to group on, names for the labels)
GROUPS = {
    "hook_type": (Label.hook_type, HOOKS),
    "topic": (Label.topic, TOPICS),
    "format": (FORMAT_GROUP_COLUMN, {key: text for key, (text, _) in FORMAT_GROUPS.items()}),
}


@router.get("/insights", response_model=InsightsOut)
def get_insights(
    window: int = Depends(window_param),
    group_by: str = Query("hook_type"),
    platform: str | None = Query(None),
    session: Session = Depends(get_session),
) -> InsightsOut:
    """What works: average score per hook, topic or format. Small groups are hidden."""
    choice(group_by, GROUPS, "group_by")
    choice(platform, PLATFORMS, "platform")
    column, names = GROUPS[group_by]
    engagement = (
        func.coalesce(Post.likes, 0)
        + func.coalesce(Post.comments, 0)
        + func.coalesce(Post.shares, 0)
    )
    stmt = (
        join_ranked(
            select(column, func.count(), func.avg(PostScore.score), func.avg(engagement)), window
        )
        .where(column.is_not(None))
        .group_by(column)
    )
    if platform:
        stmt = stmt.where(Post.platform == platform)
    rows = session.execute(stmt).all()

    shown = [r for r in rows if r[1] >= config.MIN_GROUP_SIZE]
    hidden = [r for r in rows if r[1] < config.MIN_GROUP_SIZE]
    shown.sort(key=lambda r: (-r[2], r[0]))
    return InsightsOut(
        window=window,
        group_by=group_by,
        platform=platform,
        groups=[
            InsightGroup(
                value=value,
                label=names.get(value, value),
                count=count,
                avg_score=avg_score,
                avg_engagement=avg_engagement,
            )
            for value, count, avg_score, avg_engagement in shown
        ],
        hidden_groups=len(hidden),
        hidden_posts=sum(r[1] for r in hidden),
        total_posts=sum(r[1] for r in rows),
        min_group_size=config.MIN_GROUP_SIZE,
    )
