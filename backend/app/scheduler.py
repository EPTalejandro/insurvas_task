"""Runs the searches from the Search tab in one background thread of the API server.

One thread, one search at a time: SQLite has a single writer, and two searches at once would
also share the same API quotas. The thread looks for due searches every POLL_SECONDS, and
"Run now" wakes it at once. A search scheduled while the server is off runs when it starts.
"""

import logging
import threading

from app import jobs
from app.config import get_settings
from app.db import SessionLocal
from app.httpclient import make_client

POLL_SECONDS = 15
logger = logging.getLogger(__name__)

_wake = threading.Event()
_stop = threading.Event()


def wake() -> None:
    """Look for due searches now instead of at the next poll."""
    _wake.set()


def run_due_jobs() -> int:
    """Run every search whose time has come, oldest first. Returns how many ran."""
    count = 0
    while True:
        with SessionLocal() as session, make_client() as client:
            job = jobs.next_due_job(session)
            if job is None:
                return count
            jobs.run_job(session, job, client, get_settings())
        count += 1


def _loop() -> None:
    while not _stop.is_set():
        _wake.clear()  # before looking, so a wake during a search is not lost
        try:
            run_due_jobs()
        except Exception:
            logger.exception("scheduler: a search failed")
        _wake.wait(POLL_SECONDS)


def start() -> None:
    with SessionLocal() as session:
        jobs.mark_interrupted(session)
    _stop.clear()
    threading.Thread(target=_loop, name="scheduler", daemon=True).start()


def stop() -> None:
    """Stop after the current search. The thread is a daemon, so it never blocks shutdown."""
    _stop.set()
    _wake.set()
