"""Default discovery terms. `seed` copies them into the keywords table once.

They are plain search phrases, so changing them is a one-line edit.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Keyword

DEFAULT_KEYWORDS: tuple[str, ...] = (
    "life insurance agent",
    "life insurance agency",
    "final expense insurance agent",
    "term life insurance agent",
    "IUL agent",
    "indexed universal life agent",
    "mortgage protection insurance agent",
    "annuity agent",
    "life insurance sales tips",
    "become a life insurance agent",
)


def seed_keywords(session: Session) -> int:
    """Insert missing default keywords. Returns how many were added.

    Checks before inserting so running `seed` twice does not create duplicates.
    """
    existing = set(session.scalars(select(Keyword.term)))
    added = 0
    for term in DEFAULT_KEYWORDS:
        if term not in existing:
            session.add(Keyword(term=term, platform=None, active=True))
            added += 1
    session.commit()
    return added
