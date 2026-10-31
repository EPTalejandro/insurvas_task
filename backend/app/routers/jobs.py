"""Searches: start one now or at a set time, follow its progress, cancel a scheduled one.

The work itself runs in the scheduler thread (`app.scheduler`); these routes only read and
write the `jobs` table.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs, scheduler
from app.api_common import MAX_INT, utc
from app.db import get_session
from app.models import Job, JobStep
from app.schemas import JobIn, JobOut, JobStepOut

router = APIRouter()


def _step_out(step: JobStep) -> JobStepOut:
    done, total, detail = step.done, step.total, step.detail
    live = jobs.live_progress(step.id) if step.status == "running" else None
    if live:
        done, total, detail = live
    return JobStepOut(
        step=step.step,
        label=jobs.STEPS.get(step.step, step.step),
        status=step.status,
        done=done,
        total=total,
        detail=detail,
        message=step.message,
    )


def _job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        status=job.status,
        run_at=utc(job.run_at),
        youtube_terms=job.youtube_terms,
        hashtags=job.hashtags,
        message=job.message,
        created_at=utc(job.created_at),
        started_at=utc(job.started_at),
        finished_at=utc(job.finished_at),
        steps=[_step_out(step) for step in job.steps],
    )


def _job_or_404(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="search not found")
    return job


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)
) -> list[JobOut]:
    """The latest searches, newest first, with the progress of each step."""
    return [
        _job_out(job) for job in session.scalars(select(Job).order_by(Job.id.desc()).limit(limit))
    ]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int = Path(le=MAX_INT), session: Session = Depends(get_session)) -> JobOut:
    return _job_out(_job_or_404(session, job_id))


@router.post("/jobs", response_model=JobOut, status_code=201)
def add_job(body: JobIn, session: Session = Depends(get_session)) -> JobOut:
    """Plan a search. Without run_at it starts right away."""
    try:
        job = jobs.create_job(session, body.steps, body.run_at, body.youtube_terms, body.hashtags)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    if body.run_at is None:
        scheduler.wake()
    return _job_out(job)


@router.delete("/jobs/{job_id}", status_code=204)
def cancel_job(job_id: int = Path(le=MAX_INT), session: Session = Depends(get_session)) -> None:
    """Cancel a search that has not started. One that ran or is running stays in the history."""
    job = _job_or_404(session, job_id)
    if job.status != jobs.SCHEDULED:
        raise HTTPException(status_code=409, detail="only a scheduled search can be cancelled")
    session.delete(job)
    session.commit()
