"""Helpers that record each pipeline step in the `runs` table.

Two calls per step: start_run before the work, finish_run after it.
A failed run still gets finished, so the Sources tab never shows a run stuck in "running".
"""

from sqlalchemy.orm import Session

from app.models import Run, utcnow

RUNNING = "running"
OK = "ok"
PARTIAL = "partial"  # some items worked, some failed
ERROR = "error"


def start_run(session: Session, kind: str, platform: str | None = None) -> Run:
    run = Run(kind=kind, platform=platform, status=RUNNING)
    session.add(run)
    session.commit()
    return run


def finish_run(
    session: Session,
    run: Run,
    *,
    status: str,
    items_ok: int = 0,
    items_failed: int = 0,
    quota_used: int = 0,
    message: str | None = None,
    hashtags: list[str] | None = None,
) -> Run:
    run.status = status
    run.items_ok = items_ok
    run.items_failed = items_failed
    run.quota_used = quota_used
    run.message = message
    run.hashtags = ",".join(hashtags) if hashtags else None
    run.finished_at = utcnow()
    session.commit()
    return run
