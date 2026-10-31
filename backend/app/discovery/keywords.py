"""Search terms and hashtags: the rules for the ones users add in the Sources tab.

There is no built-in list: a fresh database has none, and every term is added from the UI.
They live in the `keywords` table, which discover (YouTube search terms) and the hashtag
collector read on every run.
"""

import re

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
