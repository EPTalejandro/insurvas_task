"""Default discovery terms. `seed` copies them into the keywords table once.

They are plain search phrases, so changing them is a one-line edit. More can be added from the
Sources tab; `normalize_keyword` checks those.
"""

import re

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


# Instagram hashtags (without the #). Instagram allows 30 different hashtags per 7 days.
DEFAULT_HASHTAGS: tuple[str, ...] = (
    "lifeinsurance",
    "insuranceagent",
    "insurancebroker",
    "termlifeinsurance",
    "iul",
    "healthinsurance",  # mostly off-topic for life insurance: Gemini marks those posts irrelevant
    "insurancesales",
)


PLATFORMS = (None, "instagram")  # None: a YouTube search term; "instagram": a hashtag
TERM_LENGTH = (2, 80)
_HASHTAG = re.compile(r"^\w{1,50}$")  # Instagram hashtags are one word: letters, digits and _


def normalize_keyword(term: str, platform: str | None) -> str:
    """The term as it is stored. Raises ValueError with a message the user can read."""
    if platform not in PLATFORMS:
        raise ValueError("platform must be empty (a YouTube search term) or instagram")
    term = " ".join(term.split())
    if platform == "instagram":
        tag = term.removeprefix("#").lower()
        if not _HASHTAG.match(tag):
            raise ValueError("a hashtag is one word of letters, numbers or _, without spaces")
        return tag
    shortest, longest = TERM_LENGTH
    if not shortest <= len(term) <= longest:
        raise ValueError(f"a search term needs {shortest} to {longest} characters")
    return term


def seed_keywords(session: Session) -> int:
    """Insert missing default keywords. Returns how many were added.

    Checks before inserting so running `seed` twice does not create duplicates.
    """
    existing = {
        (k.term, k.platform) for k in session.execute(select(Keyword.term, Keyword.platform))
    }
    wanted = [(term, None) for term in DEFAULT_KEYWORDS]
    wanted += [(tag, "instagram") for tag in DEFAULT_HASHTAGS]
    added = 0
    for term, platform in wanted:
        if (term, platform) not in existing:
            session.add(Keyword(term=term, platform=platform, active=True))
            added += 1
    session.commit()
    return added
