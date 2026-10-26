"""The `rank` step: rewrite post_scores and competitor_scores for every window."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import runs
from app.models import (
    HASHTAG_KIND,
    Competitor,
    CompetitorScore,
    Creator,
    Label,
    Post,
    PostScore,
    Run,
)
from app.ranking import config
from app.ranking.scoring import (
    PostInput,
    ScoredPost,
    as_utc,
    score_competitor,
    score_posts,
)


def load_inputs(
    session: Session, now: datetime
) -> tuple[list[PostInput], dict[int, Label | None], dict[int, int | None]]:
    """Read the last 90 days of posts. Also returns each post's label and competitor id."""
    cutoff = (now - timedelta(days=config.BASELINE_DAYS)).replace(tzinfo=None)  # stored naive UTC
    rows = session.execute(
        select(Post, Creator, Competitor.status, Label)
        .join(Creator, Post.creator_id == Creator.id)
        .outerjoin(Competitor, Creator.competitor_id == Competitor.id)
        .outerjoin(Label, Label.post_id == Post.id)
        .where(Post.published_at >= cutoff)
    )
    inputs, labels, competitor_of = [], {}, {}
    for post, creator, competitor_status, label in rows:
        is_hashtag = creator.kind == HASHTAG_KIND
        # Competitor posts need an active competitor. Hashtag posts have none, so their
        # caption must look US-based instead.
        if is_hashtag:
            allowed = post.location_status in config.HASHTAG_LOCATIONS
        else:
            allowed = competitor_status == "active"
        # An unlabeled post still counts; only an explicit "not relevant" or "flex" removes it.
        counts = (
            allowed
            and creator.is_relevant
            and (label is None or (label.is_relevant and not label.is_flex))
        )
        inputs.append(
            PostInput(
                post_id=post.id,
                creator_id=creator.id,
                platform=post.platform,
                published_at=as_utc(post.published_at),
                likes=post.likes,
                comments=post.comments,
                shares=post.shares,
                views=post.views,
                followers=creator.followers,
                counts=counts,
                known_author=not is_hashtag,
                format=post.format,
            )
        )
        labels[post.id] = label
        competitor_of[post.id] = creator.competitor_id
    return inputs, labels, competitor_of


def rank_all(session: Session, now: datetime | None = None) -> Run:
    now = now or datetime.now(UTC)
    run = runs.start_run(session, "rank")
    try:
        inputs, labels, competitor_of = load_inputs(session, now)
        session.execute(delete(PostScore))
        session.execute(delete(CompetitorScore))

        summary = []
        post_rows = competitor_rows = 0
        for window in config.WINDOWS:
            results = score_posts(inputs, window, now)
            session.add_all(
                PostScore(
                    post_id=r.post_id,
                    window_days=window,
                    adjusted_engagement=r.adjusted_engagement,
                    engagement_rate=r.engagement_rate,
                    outperformance=r.outperformance,
                    score=r.score,
                    rank_in_platform=r.rank_in_platform,
                    reason=r.reason,
                )
                for r in results
            )

            by_competitor: dict[int, list[ScoredPost]] = {}
            for r in results:
                competitor_id = competitor_of[r.post_id]
                if competitor_id is None:
                    continue
                label = labels[r.post_id]
                scored = ScoredPost(
                    post_id=r.post_id,
                    score=r.score,
                    topic=label.topic if label else None,
                    hook_type=label.hook_type if label else None,
                )
                by_competitor.setdefault(competitor_id, []).append(scored)

            for competitor_id, scored_posts in by_competitor.items():
                result = score_competitor(scored_posts, window)
                session.add(
                    CompetitorScore(
                        competitor_id=competitor_id,
                        window_days=window,
                        score=result.score,
                        posts_count=result.posts_count,
                        consistency=result.consistency,
                        best_post_id=result.best_post_id,
                        top_topic=result.top_topic,
                        top_hook=result.top_hook,
                        low_sample=result.low_sample,
                    )
                )
            post_rows += len(results)
            competitor_rows += len(by_competitor)
            summary.append(f"{window}d: {len(results)} posts, {len(by_competitor)} competitors")
        session.commit()
    except Exception as error:
        session.rollback()  # keep the previous scores instead of a half-written set
        runs.finish_run(session, run, status=runs.ERROR, message=str(error)[:200])
        raise
    return runs.finish_run(
        session, run, status=runs.OK, items_ok=post_rows, message="; ".join(summary)
    )
