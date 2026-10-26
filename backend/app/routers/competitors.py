from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api_common import (
    MAX_INT,
    PostFilters,
    account_out,
    ranked_posts_stmt,
    to_post_out,
    window_param,
)
from app.db import get_session
from app.models import Competitor, CompetitorScore, Post, PostScore
from app.ranking import config
from app.schemas import (
    BestPostOut,
    CompetitorDetail,
    CompetitorOut,
    CompetitorsPage,
    WindowScoreOut,
)

router = APIRouter()
TOP_POSTS_IN_DETAIL = 10


def _best_posts(session: Session, post_ids: list[int], window: int) -> dict[int, BestPostOut]:
    if not post_ids:
        return {}
    rows = session.execute(
        select(Post.id, Post.url, Post.title, PostScore.score)
        .outerjoin(PostScore, and_(PostScore.post_id == Post.id, PostScore.window_days == window))
        .where(Post.id.in_(post_ids))
    )
    return {r.id: BestPostOut(id=r.id, url=r.url, title=r.title, score=r.score) for r in rows}


def _competitor_out(
    competitor: Competitor,
    score: CompetitorScore | None,
    best: BestPostOut | None,
    rank: int | None,
) -> CompetitorOut:
    """A competitor with no score in this window still gets an entry, with empty numbers."""
    return CompetitorOut(
        id=competitor.id,
        name=competitor.name,
        kind=competitor.kind,
        website=competitor.website,
        status=competitor.status,
        rank=rank,
        score=score.score if score else None,
        posts_count=score.posts_count if score else 0,
        consistency=score.consistency if score else None,
        low_sample=score.low_sample if score else True,
        top_topic=score.top_topic if score else None,
        top_hook=score.top_hook if score else None,
        best_post=best,
        accounts=[account_out(creator) for creator in competitor.creators],
    )


@router.get("/competitors", response_model=CompetitorsPage)
def list_competitors(
    window: int = Depends(window_param),
    include_low_sample: bool = False,
    session: Session = Depends(get_session),
) -> CompetitorsPage:
    """The leaderboard. Competitors with too few posts in the window are hidden by default."""
    rows = session.execute(
        select(Competitor, CompetitorScore)
        .join(
            CompetitorScore,
            and_(
                CompetitorScore.competitor_id == Competitor.id,
                CompetitorScore.window_days == window,
            ),
        )
        .where(Competitor.status == "active")
        .order_by(CompetitorScore.score.desc(), Competitor.id)
    ).all()
    visible = [(c, s) for c, s in rows if include_low_sample or not s.low_sample]
    best = _best_posts(session, [s.best_post_id for _, s in visible if s.best_post_id], window)
    items = [
        _competitor_out(c, s, best.get(s.best_post_id), rank)
        for rank, (c, s) in enumerate(visible, start=1)
    ]
    return CompetitorsPage(
        window=window,
        items=items,
        total=len(items),
        hidden_low_sample=len(rows) - len(visible),
    )


@router.get("/competitors/{competitor_id}", response_model=CompetitorDetail)
def get_competitor(
    competitor_id: int = Path(le=MAX_INT),
    window: int = Depends(window_param),
    session: Session = Depends(get_session),
) -> CompetitorDetail:
    competitor = session.get(Competitor, competitor_id)
    if competitor is None:
        raise HTTPException(status_code=404, detail="competitor not found")

    scores = {
        s.window_days: s
        for s in session.scalars(
            select(CompetitorScore).where(CompetitorScore.competitor_id == competitor_id)
        )
    }
    score = scores.get(window)
    rank = None
    if score is not None and not score.low_sample:
        better = session.scalar(
            select(func.count())
            .select_from(CompetitorScore)
            .join(Competitor, Competitor.id == CompetitorScore.competitor_id)
            .where(
                CompetitorScore.window_days == window,
                CompetitorScore.score > score.score,
                CompetitorScore.low_sample.is_(False),
                Competitor.status == "active",
            )
        )
        rank = (better or 0) + 1

    best = _best_posts(
        session, [score.best_post_id] if score and score.best_post_id else [], window
    )
    top = session.execute(
        ranked_posts_stmt(window, PostFilters(competitor_id=competitor_id)).limit(
            TOP_POSTS_IN_DETAIL
        )
    ).all()
    return CompetitorDetail(
        window=window,
        competitor=_competitor_out(
            competitor, score, best.get(score.best_post_id) if score else None, rank
        ),
        scores_by_window=[
            WindowScoreOut(
                window=w,
                score=scores[w].score,
                posts_count=scores[w].posts_count,
                consistency=scores[w].consistency,
                low_sample=scores[w].low_sample,
            )
            for w in config.WINDOWS
            if w in scores
        ],
        top_posts=[to_post_out(*row) for row in top],
    )
