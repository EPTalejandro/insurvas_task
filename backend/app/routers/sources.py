"""What the app collected from and when: pipeline runs, the search keywords and the hashtag budget.

Keywords are the only thing the web can change. They are used on the next pipeline run
(`refresh`), which still runs from the command line.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api_common import MAX_INT, utc
from app.budget import HASHTAG_WINDOW_DAYS, hashtag_budget, searches_from_runs
from app.db import get_session
from app.discovery.keywords import normalize_keyword
from app.models import Keyword, Run
from app.schemas import (
    HashtagBudgetOut,
    HashtagSlotOut,
    KeywordIn,
    KeywordOut,
    KeywordPatch,
    RunOut,
)

router = APIRouter()


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)
) -> list[RunOut]:
    """The latest pipeline runs, newest first."""
    runs = session.scalars(select(Run).order_by(Run.id.desc()).limit(limit))
    return [
        RunOut.model_validate(run).model_copy(
            update={"started_at": utc(run.started_at), "finished_at": utc(run.finished_at)}
        )
        for run in runs
    ]


@router.get("/keywords", response_model=list[KeywordOut])
def list_keywords(session: Session = Depends(get_session)) -> list[KeywordOut]:
    return [
        KeywordOut.model_validate(k) for k in session.scalars(select(Keyword).order_by(Keyword.id))
    ]


@router.post("/keywords", response_model=KeywordOut, status_code=201)
def add_keyword(body: KeywordIn, session: Session = Depends(get_session)) -> KeywordOut:
    """Add a YouTube search term (platform empty) or an Instagram hashtag."""
    try:
        term = normalize_keyword(body.term, body.platform)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    # NULL platforms never clash in SQLite's unique index, so duplicates are checked here.
    same_platform = (
        Keyword.platform.is_(None) if body.platform is None else Keyword.platform == body.platform
    )
    duplicate = session.scalar(
        select(Keyword.id).where(func.lower(Keyword.term) == term.lower(), same_platform)
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail=f"'{term}' is already in the list")
    keyword = Keyword(term=term, platform=body.platform, active=True)
    session.add(keyword)
    session.commit()
    return KeywordOut.model_validate(keyword)


def _keyword_or_404(session: Session, keyword_id: int) -> Keyword:
    keyword = session.get(Keyword, keyword_id)
    if keyword is None:
        raise HTTPException(status_code=404, detail="keyword not found")
    return keyword


@router.patch("/keywords/{keyword_id}", response_model=KeywordOut)
def update_keyword(
    body: KeywordPatch,
    keyword_id: int = Path(le=MAX_INT),
    session: Session = Depends(get_session),
) -> KeywordOut:
    """Turn a term on or off. Inactive terms are kept but not searched."""
    keyword = _keyword_or_404(session, keyword_id)
    keyword.active = body.active
    session.commit()
    return KeywordOut.model_validate(keyword)


@router.delete("/keywords/{keyword_id}", status_code=204)
def delete_keyword(
    keyword_id: int = Path(le=MAX_INT), session: Session = Depends(get_session)
) -> None:
    """Remove a term. A hashtag searched this week keeps its slot: the slot is in the runs."""
    session.delete(_keyword_or_404(session, keyword_id))
    session.commit()


@router.get("/hashtag-budget", response_model=HashtagBudgetOut)
def get_hashtag_budget(session: Session = Depends(get_session)) -> HashtagBudgetOut:
    """How many of Instagram's 30 weekly hashtag slots are taken, from the runs' hashtags."""
    now = datetime.now(UTC)
    cutoff = (now - timedelta(days=HASHTAG_WINDOW_DAYS)).replace(tzinfo=None)  # stored naive UTC
    rows = session.execute(
        select(Run.hashtags, Run.started_at).where(
            Run.hashtags.is_not(None), Run.started_at >= cutoff
        )
    ).all()
    budget = hashtag_budget(searches_from_runs(rows), now)
    return HashtagBudgetOut(
        limit=budget.limit,
        used=budget.used,
        free=budget.free,
        next_free_at=budget.next_free_at,
        slots=[
            HashtagSlotOut(tag=tag, frees_at=frees_at)
            for tag, frees_at in sorted(budget.slots.items(), key=lambda slot: (slot[1], slot[0]))
        ],
    )
