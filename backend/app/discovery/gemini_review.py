"""Gemini as a second opinion on accounts the rules cannot settle.

Two questions: "is this a life insurance agent or agency?" (for accounts the rules are unsure
about) and "is it based in the US?" (for accounts with no country and no clear text signals).
Gemini must quote the words that support its answer, and an answer only counts when the quote
really appears in the text we gave it. That keeps a made-up answer from changing the data.
"""

import json
import re
from dataclasses import dataclass, field
from itertools import batched
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.gemini_client import GeminiJson

BATCH_SIZE = 10
BIO_CHARS = 500


class CreatorVerdict(BaseModel):
    creator_id: int
    kind: Literal["agent", "agency", "carrier", "other"]
    united_states: Literal["yes", "no", "unknown"]
    evidence: str


@dataclass(frozen=True)
class CreatorBrief:
    """What Gemini gets to read about an account."""

    creator_id: int
    name: str
    bio: str | None
    recent_posts: list[str] = field(default_factory=list)  # titles and the start of descriptions

    def text(self) -> str:
        return " ".join([self.name, self.bio or "", *self.recent_posts])


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_is_in(quote: str, brief: CreatorBrief) -> bool:
    """Is the quoted evidence really part of what Gemini was shown?"""
    wanted = _normalize(quote)
    return bool(wanted) and wanted in _normalize(brief.text())


def build_prompt(briefs: list[CreatorBrief]) -> str:
    accounts = "\n".join(
        json.dumps(
            {
                "creator_id": brief.creator_id,
                "name": brief.name,
                "bio": (brief.bio or "")[:BIO_CHARS],
                "recent_posts": brief.recent_posts,
            },
            ensure_ascii=False,
        )
        for brief in briefs
    )
    return f"""You decide what kind of account a social media account is, and where it is based.
Return a JSON list with exactly one object per account, using the creator_id given.

kind:
- agent: a person who sells life insurance (or final expense, IUL, annuities)
- agency: a company or team that sells life insurance or recruits and trains agents to sell it
- carrier: an insurance company
- other: anything else (news, education for consumers, an unrelated business or hobby)

united_states:
- yes: only if the text clearly shows the account is based in the United States (a US state or
  city, a US phone number, "licensed in <state>", US-only products or laws)
- no: only if the text clearly shows another country
- unknown: in every other case. Do not guess.

evidence: words copied exactly from the account's text (at most 25 words) that support your
united_states answer. Empty when the answer is unknown.

Accounts, one JSON object per line:
{accounts}
"""


class GeminiReviewer:
    def __init__(self, gemini: GeminiJson) -> None:
        self._gemini = gemini

    def review(self, briefs: list[CreatorBrief]) -> dict[int, CreatorVerdict | None]:
        """A verdict per account, or None when Gemini gave no usable answer for it."""
        verdicts: dict[int, CreatorVerdict | None] = {brief.creator_id: None for brief in briefs}
        for chunk in batched(briefs, BATCH_SIZE, strict=False):
            answers = self._gemini.ask(build_prompt(list(chunk)), list[CreatorVerdict])
            if answers is None:
                continue
            by_id = {brief.creator_id: brief for brief in chunk}
            for answer in answers:
                try:
                    verdict = CreatorVerdict.model_validate(answer)
                except ValidationError:
                    continue
                brief = by_id.get(verdict.creator_id)
                if brief is None:
                    continue  # an id we did not ask about
                if verdict.united_states != "unknown" and not quote_is_in(verdict.evidence, brief):
                    verdict = verdict.model_copy(
                        update={
                            "united_states": "unknown",
                            "evidence": "quote not found in the text",
                        }
                    )
                verdicts[verdict.creator_id] = verdict
        return verdicts
