from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api_common import (
    MAX_INT,
    PostFilters,
    post_filters,
    ranked_count_stmt,
    ranked_posts_stmt,
    to_post_out,
    too_new_count,
    window_param,
)
from app.db import get_session
from app.schemas import PostsPage

router = APIRouter()


@router.get("/posts", response_model=PostsPage)
def list_posts(
    window: int = Depends(window_param),
    filters: PostFilters = Depends(post_filters),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=MAX_INT),
    session: Session = Depends(get_session),
) -> PostsPage:
    """Ranked posts of a window, best first."""
    total = session.scalar(ranked_count_stmt(window, filters)) or 0
    rows = session.execute(ranked_posts_stmt(window, filters).limit(limit).offset(offset)).all()
    return PostsPage(
        window=window,
        items=[to_post_out(*row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        too_new=too_new_count(session, filters, datetime.now(UTC)),
    )
