from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query
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
from app.models import Post
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


def _post_or_404(session: Session, post_id: int) -> Post:
    post = session.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post not found")
    return post


# PUT, not POST: a bodyless cross-origin POST is a "simple" request that browsers send without
# asking first. PUT always needs a CORS preflight, so other sites cannot mark posts.
@router.put("/posts/{post_id}/seen", status_code=204)
def mark_seen(post_id: int = Path(le=MAX_INT), session: Session = Depends(get_session)) -> None:
    """Opening a post's link marks it as seen. The first time is kept."""
    post = _post_or_404(session, post_id)
    if post.seen_at is None:
        post.seen_at = datetime.now(UTC)
        session.commit()


@router.delete("/posts/{post_id}/seen", status_code=204)
def mark_unseen(post_id: int = Path(le=MAX_INT), session: Session = Depends(get_session)) -> None:
    """Undo: the post goes back to the New list."""
    post = _post_or_404(session, post_id)
    post.seen_at = None
    session.commit()
