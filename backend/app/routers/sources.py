"""What the app collected from and when: pipeline runs and the search keywords."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api_common import utc
from app.db import get_session
from app.models import Keyword, Run
from app.schemas import KeywordOut, RunOut

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
