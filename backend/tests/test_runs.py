from sqlalchemy import select

from app import runs
from app.models import Run


def test_run_is_started_then_finished(session):
    run = runs.start_run(session, kind="collect", platform="youtube")
    assert run.status == runs.RUNNING
    assert run.finished_at is None

    runs.finish_run(session, run, status=runs.PARTIAL, items_ok=8, items_failed=2, quota_used=5)

    saved = session.scalars(select(Run)).one()
    assert saved.kind == "collect"
    assert saved.platform == "youtube"
    assert saved.status == "partial"
    assert (saved.items_ok, saved.items_failed, saved.quota_used) == (8, 2, 5)
    assert saved.finished_at is not None
