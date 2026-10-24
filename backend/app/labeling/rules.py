"""Rules labeler: keyword and pattern matching. Free, explainable, always available.

It is also the fallback when Gemini fails. Everything here is a pure function.
Rules are heuristics: they look at the opening line for the hook and count keywords
for the topic. Gemini is better with nuance (sarcasm, mixed topics).
"""

import hashlib
import re
from dataclasses import dataclass

from app.labeling.taxonomy import CTAS, HOOKS, TOPICS

HOOK_MAX_CHARS = 150
CTA_SCAN_CHARS = 500  # CTAs sit near the top; the rest of a description is boilerplate
TITLE_WEIGHT = 2  # a keyword in the title says more than one buried in the description


@dataclass(frozen=True)
class LabelResult:
    topic: str
    hook_type: str
    hook_text: str | None
    cta: str
    is_relevant: bool
    confidence: float


def _words(*terms: str) -> re.Pattern[str]:
    """Match any of the terms as whole words, ignoring case."""
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b", re.IGNORECASE)


# Order matters only for ties: the first topic listed wins.
TOPIC_KEYWORDS: dict[str, re.Pattern[str]] = {
    "final_expense": _words("final expense", "burial", "funeral", "burial insurance"),
    "mortgage_protection": _words("mortgage protection", "mortgage life", "mortgage insurance"),
    "iul": _words("iul", "indexed universal", "index universal"),
    "infinite_banking": _words("infinite banking", "bank on yourself", "your own bank"),
    "living_benefits": _words(
        "living benefits", "living benefit", "chronic illness", "critical illness"
    ),
    "term_life": _words("term life", "term insurance", "level term", "term policy"),
    "whole_life": _words("whole life", "permanent life", "cash value", "permanent insurance"),
    "annuities_retirement": _words(
        "annuity", "annuities", "retirement", "401k", "401(k)", "pension", "roth"
    ),
    "estate_and_tax": _words(
        "estate", "inheritance", "tax-free", "tax free", "trust", "legacy", "estate planning"
    ),
    "agent_recruiting": _words(
        "join my team", "join our team", "become an agent", "hiring agents", "recruit",
        "agency owner", "downline", "insurance career", "become a life insurance agent",
    ),
    "sales_training": _words(
        "sales", "leads", "lead generation", "cold call", "objection", "objections", "script",
        "prospecting", "closing", "close more", "appointments", "book of business", "chargeback",
        "chargebacks", "life exam", "licensing exam", "license exam", "state exam", "exam prep",
        "quiz", "telesales",
    ),
    "client_story": _words(
        "my client", "client story", "case study", "claim paid", "paid out", "paid the claim",
        "testimonial", "families protected", "premium placed",
    ),
    "myth_busting": _words("myth", "myths", "debunk", "misconception", "scam", "mistakes"),
    "general_education": _words(
        "what is", "how does", "explained", "how it works", "beginner", "101", "guide"
    ),
}  # fmt: skip

_STATISTIC = re.compile(
    r"\$\s?\d|\d\s?%|\b\d{1,3}(?:,\d{3})+\b|\b\d+\s?(?:k|m)\b|\bmillion\b|\bbillion\b",
    re.IGNORECASE,
)
_HOW_TO_LIST = re.compile(
    r"\bhow to\b"
    r"|\b(?:top\s+)?\d+\s+(?:ways|tips|steps|things|reasons|mistakes|secrets|questions)\b",
    re.IGNORECASE,
)
# Checked in this order; the first pattern that matches the opening line wins.
HOOK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("how_to_list", _HOW_TO_LIST),
    ("statistic", _STATISTIC),
    ("question", re.compile(r"\?")),
    ("contrarian", _words(
        "myth", "myths", "lie", "lies", "wrong", "actually", "the truth", "unpopular opinion",
        "overrated", "nobody tells", "they don't want", "is a scam",
    )),
    ("warning", _words(
        "warning", "avoid", "never", "don't", "do not", "stop", "before you", "mistake",
        "mistakes", "beware", "danger",
    )),
    ("personal_story", re.compile(r"^(?:i|i'm|i've|my|when i|how i|story time)\b", re.IGNORECASE)),
    ("social_proof", _words(
        "review", "reviews", "testimonial", "clients say", "5 star", "rated", "trusted by",
        "families helped", "paid out",
    )),
    ("curiosity_gap", _words(
        "secret", "you won't believe", "here's why", "this is why", "the one thing",
        "what happens", "wait until", "nobody",
    )),
    ("direct_offer", _words(
        "free quote", "get a quote", "call now", "dm me", "book a call", "click the link",
        "apply now", "limited time", "free consultation",
    )),
]  # fmt: skip

_US_PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
# First match wins, so the more commercial CTAs come first. "Subscribe" is on almost every
# YouTube description, so it goes last.
CTA_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("join_team", _words(
        "join my team", "join our team", "become an agent", "apply to join", "now hiring",
    )),
    ("book_call", _words(
        "book a call", "schedule a call", "book your", "calendly", "free consultation",
        "free quote", "get a quote",
    )),
    ("call_or_text", re.compile(
        r"\b(?:call or text|call us|call me|text me|text us)\b", re.IGNORECASE
    )),
    ("comment_or_dm_keyword", re.compile(
        r"\bcomment\s+[\"“']?\w+|\bdm\s+(?:me|us)\b|\bsend me a dm\b|\bmessage me\b", re.IGNORECASE
    )),
    ("link_in_bio", _words(
        "link in bio", "link in my bio", "link in description", "link below", "linktree",
        "click the link",
    )),
    ("follow_subscribe", _words("subscribe", "follow me", "follow us", "hit the bell")),
]  # fmt: skip


def content_hash(title: str | None, text: str | None) -> str:
    """Changes only when the words change, so unchanged posts are not labeled again."""
    return hashlib.sha256(f"{title or ''}\x00{text or ''}".encode()).hexdigest()


def opening_line(title: str | None, text: str | None) -> str | None:
    """The hook: a YouTube title, or the first line of an Instagram caption."""
    source = title or next((line for line in (text or "").splitlines() if line.strip()), "")
    line = " ".join(source.split())
    return line[:HOOK_MAX_CHARS] or None


def detect_topic(title: str | None, text: str | None) -> tuple[str, int]:
    """Returns (topic, weighted keyword hits). 'other' when nothing matches."""
    best_topic, best_hits = "other", 0
    for topic, pattern in TOPIC_KEYWORDS.items():
        hits = TITLE_WEIGHT * len(pattern.findall(title or "")) + len(pattern.findall(text or ""))
        if hits > best_hits:  # strict ">" keeps the first-listed topic on ties
            best_topic, best_hits = topic, hits
    return best_topic, best_hits


def detect_hook(hook_text: str | None) -> str:
    if not hook_text:
        return "none"
    for hook, pattern in HOOK_PATTERNS:
        if pattern.search(hook_text):
            return hook
    return "none"


def detect_cta(title: str | None, text: str | None) -> str:
    scanned = f"{title or ''}\n{(text or '')[:CTA_SCAN_CHARS]}"
    if _US_PHONE.search(scanned):
        return "call_or_text"
    for cta, pattern in CTA_PATTERNS:
        if pattern.search(scanned):
            return cta
    return "none"


def label_post(title: str | None, text: str | None) -> LabelResult:
    topic, hits = detect_topic(title, text)
    hook_text = opening_line(title, text)
    hook_type = detect_hook(hook_text)
    # Confidence is only a rough "how much evidence": more keyword hits, more trust.
    confidence = 0.3 if hits == 0 else round(min(0.9, 0.4 + 0.1 * hits), 2)
    return LabelResult(
        topic=topic,
        hook_type=hook_type,
        hook_text=hook_text,
        cta=detect_cta(title, text),
        # Rules cannot judge relevance, so every post counts. Gemini can mark posts irrelevant.
        is_relevant=True,
        confidence=confidence,
    )


assert set(TOPIC_KEYWORDS) <= set(TOPICS), "rules use a topic missing from the taxonomy"
assert {h for h, _ in HOOK_PATTERNS} <= set(HOOKS), "rules use a hook missing from the taxonomy"
assert {c for c, _ in CTA_PATTERNS} | {"call_or_text"} <= set(CTAS), "unknown CTA in rules"
