"""Decide whether an account is US-based, and keep the evidence.

YouTube's `country` field is the best signal but owners often leave it empty. For those
accounts we look for text signals in the bio and in the posts we collected.
`assess_location` is pure; `update_locations` is the thin database step around it.
"""

import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.discovery.gemini_review import CreatorBrief, GeminiReviewer
from app.models import HASHTAG_KIND, Creator, Post

US = "us"  # the channel says its country is US
LIKELY_US = "likely_us"  # strong text signals
UNVERIFIED = "unverified"  # not enough evidence either way
NON_US = "non_us"
PROBABLE_US = "probable_us"  # posts only: an English caption with US cues, but no hard proof

# A US-format phone number, or the words licensed US agents put in their bios.
_PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
_LICENSE = re.compile(r".{0,25}(?:\bNPN\b|national producer|licensed in\b).{0,25}", re.IGNORECASE)

# Signals of the Indian insurance market (the other market that showed up in discovery).
_NON_US = re.compile(
    r"₹|\bIndia\b|\bLIC\b|IRDAI|\blakh\b|\bcrore\b|\bRs\.?\s?\d|\b[a-z0-9-]+\.in\b"
    r"|[ऀ-ॿఀ-౿]"  # Devanagari and Telugu script
)
NON_US_MIN_HITS = 3  # one mention ("I visited India") proves nothing

# Weak signals: they only get a note in the evidence, never a status on their own.
_STATE_NAMES = re.compile(
    r"\b(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida"
    r"|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland"
    r"|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada"
    r"|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio"
    r"|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee"
    r"|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming)\b"
)
_US_TERMS = re.compile(
    r"\b(?:IRS|401\(?k\)?|Medicare|Social Security|FICO|IUL|final expense|mortgage protection)\b",
    re.IGNORECASE,
)
RECENT_POSTS_FOR_REVIEW = 3  # posts shown to Gemini besides the bio
SAMPLE_CHARS = 150
WEAK_STATE_HITS = 3
WEAK_TERM_HITS = 5

# --- Captions of posts whose author we cannot see (hashtag results) ---
_HASHTAG_MENTION_URL = re.compile(r"[#@]\w+|https?://\S+|www\.\S+")
_ENGLISH_WORDS = re.compile(
    r"\b(?:the|and|you|your|for|with|that|this|are|have|life|insurance|family|policy|coverage"
    r"|will|can|get|how|is|of|to|in|it|what|when|why)\b",
    re.IGNORECASE,
)
ENGLISH_MIN_HITS = 3
LATIN_MIN_RATIO = 0.95
# One of these is enough: a currency or a place that is not the US.
_NON_US_PLACES = re.compile(
    r"₹|£|€|\b(?:India|UK|Nigeria|Kenya|Ghana|Uganda|Philippines|Pakistan|Canada|Australia"
    r"|Indonesia|Malaysia|Singapore|Dubai|UAE|South Africa|Zimbabwe)\b"
)
_US_TIMEZONES = re.compile(r"\b(?:EST|EDT|CST|CDT|MST|MDT|PST|PDT)\b")
_DOLLARS = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class Location:
    status: str
    evidence: str | None


def _clean(text: str) -> str:
    return " ".join(text.split())


def assess_location(country: str | None, bio: str | None, texts: list[str]) -> Location:
    """texts are the titles and descriptions of the account's collected posts."""
    if country:
        status = US if country.upper() == "US" else NON_US
        return Location(status, f"channel country: {country.upper()}")

    blob = "\n".join([bio or "", *texts])

    non_us_hits = _NON_US.findall(blob)
    if len(non_us_hits) >= NON_US_MIN_HITS:
        return Location(
            NON_US, f"{len(non_us_hits)} Indian-market signals, e.g. {non_us_hits[0]!r}"
        )

    phone = _PHONE.search(blob)
    if phone:
        return Location(LIKELY_US, f"US phone number {phone.group()}")
    licence = _LICENSE.search(blob)
    if licence:
        return Location(LIKELY_US, f"license mention: {_clean(licence.group())!r}")

    states = len(_STATE_NAMES.findall(blob))
    terms = len(_US_TERMS.findall(blob))
    if states >= WEAK_STATE_HITS or terms >= WEAK_TERM_HITS:
        return Location(UNVERIFIED, f"weak US signals: {states} state names, {terms} US terms")
    return Location(UNVERIFIED, None)


def _is_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    latin = sum(c.isascii() for c in letters) / len(letters)
    return latin >= LATIN_MIN_RATIO and len(_ENGLISH_WORDS.findall(text)) >= ENGLISH_MIN_HITS


def assess_caption(caption: str | None) -> Location:
    """Judge a hashtag post from its caption alone. Never says `us`: there is no proof."""
    caption = caption or ""
    text = _HASHTAG_MENTION_URL.sub(" ", caption)  # tags are English words in any language
    if not any(c.isalpha() for c in text):
        return Location(UNVERIFIED, "caption has no text")

    place = _NON_US_PLACES.search(caption)
    if place:
        return Location(NON_US, f"non-US marker: {place.group()!r}")
    indian = _NON_US.findall(caption)
    if len(indian) >= NON_US_MIN_HITS:
        return Location(NON_US, f"{len(indian)} Indian-market signals, e.g. {indian[0]!r}")

    # Hard evidence first: a Spanish-language US agent with a license number is still US.
    phone = _PHONE.search(caption)
    if phone:
        return Location(LIKELY_US, f"US phone number {phone.group()}")
    licence = _LICENSE.search(caption)
    if licence:
        return Location(LIKELY_US, f"license mention: {_clean(licence.group())!r}")

    if not _is_english(text):
        return Location(NON_US, "caption is not in English")

    cues = {m.group().lower() for m in _STATE_NAMES.finditer(caption)}
    cues |= {m.group().lower() for m in _US_TERMS.finditer(caption)}
    cues |= {m.group() for m in _DOLLARS.finditer(caption)}
    cues |= {m.group() for m in _US_TIMEZONES.finditer(caption)}
    if cues:
        return Location(PROBABLE_US, f"English caption with US cues: {', '.join(sorted(cues)[:4])}")
    return Location(UNVERIFIED, "English caption with no US cue")


def update_post_locations(session: Session) -> Counter[str]:
    """Judge the caption of every hashtag post. Returns how many posts are in each status."""
    posts = session.scalars(
        select(Post)
        .join(Creator, Post.creator_id == Creator.id)
        .where(Creator.kind == HASHTAG_KIND)
    ).all()
    for post in posts:
        location = assess_caption(post.text)
        post.location_status = location.status
        post.location_evidence = location.evidence
    session.commit()
    return Counter(post.location_status for post in posts)


def inherited_location(siblings: list[Creator]) -> Location | None:
    """An account with no evidence can lean on a US-verified account of the same competitor."""
    for sibling in siblings:
        if sibling.location_status in (US, LIKELY_US):
            proof = sibling.location_evidence or sibling.location_status
            return Location(
                LIKELY_US, f"same competitor as {sibling.platform} {sibling.handle}: {proof}"
            )
    return None


def _texts_of(session: Session, creator: Creator) -> list[str]:
    posts = session.execute(
        select(Post.title, Post.text).where(Post.creator_id == creator.id)
    ).all()
    return [part for post in posts for part in post if part]


def _apply(creator: Creator, location: Location) -> None:
    creator.location_status = location.status
    creator.location_evidence = location.evidence


def _ask_gemini(session: Session, unverified: list[Creator], reviewer: GeminiReviewer) -> None:
    """A second opinion on the accounts without evidence. Only answers with a real quote count."""
    briefs = []
    for creator in unverified:
        recent = session.execute(
            select(Post.title, Post.text)
            .where(Post.creator_id == creator.id)
            .order_by(Post.published_at.desc())
            .limit(RECENT_POSTS_FOR_REVIEW)
        ).all()
        samples = [
            f"{title or ''}: {(text or '')[:SAMPLE_CHARS]}".strip(": ") for title, text in recent
        ]
        briefs.append(CreatorBrief(creator.id, creator.name, creator.bio, samples))
    verdicts = reviewer.review(briefs)
    for creator in unverified:
        verdict = verdicts.get(creator.id)
        if verdict is None or verdict.united_states == "unknown":
            continue
        # Gemini's reading is a judgment, not hard proof like a phone number: probable, not likely.
        status = PROBABLE_US if verdict.united_states == "yes" else NON_US
        _apply(creator, Location(status, f"Gemini quoted: {verdict.evidence!r}"))


def update_locations(session: Session, reviewer: GeminiReviewer | None = None) -> Counter[str]:
    """Re-assess the accounts of competitors that have no country, using their collected posts.

    Order: the text rules first, then Gemini for the accounts still unverified, then an account
    with no evidence can lean on a US-verified account of the same competitor. A non-US account
    is switched off; its competitor is excluded only when no other account of it is left.
    Returns how many accounts are in each status.
    """
    creators = list(
        session.scalars(
            select(Creator).where(Creator.competitor_id.is_not(None), Creator.is_relevant)
        )
    )
    creators.sort(key=lambda creator: (creator.platform != "youtube", creator.id))
    judged = [creator for creator in creators if not creator.country]  # a country settles it

    for creator in judged:
        _apply(creator, assess_location(None, creator.bio, _texts_of(session, creator)))
    if reviewer is not None:
        unverified = [c for c in judged if c.location_status == UNVERIFIED]
        if unverified:
            _ask_gemini(session, unverified, reviewer)
    for creator in judged:
        if creator.location_status == UNVERIFIED:
            siblings = [
                c for c in creator.competitor.creators if c.id != creator.id and c.is_relevant
            ]
            inherited = inherited_location(siblings)
            if inherited:
                _apply(creator, inherited)
    for creator in judged:
        if creator.location_status == NON_US:
            creator.is_relevant = False
            if not any(c.is_relevant for c in creator.competitor.creators):
                creator.competitor.status = "excluded"
    session.commit()
    return Counter(
        session.scalars(
            select(Creator.location_status).where(
                Creator.competitor_id.is_not(None), Creator.is_relevant
            )
        )
    )
