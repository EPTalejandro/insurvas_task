"""Rules that decide whether an account is a life insurance agent or agency we should track.

Pure functions. Gemini will later help with the unsure cases; these rules are the fallback.
"""

import re
from dataclasses import dataclass

# Insurance companies and insurtechs. They are not the competitors we want to learn from.
CARRIERS = (
    "state farm", "allstate", "geico", "progressive", "farmers insurance", "liberty mutual",
    "nationwide", "usaa", "metlife", "prudential", "new york life", "northwestern mutual",
    "massmutual", "mass mutual", "lincoln financial", "transamerica", "aflac", "pacific life",
    "guardian life", "principal financial", "aig", "john hancock", "globe life",
    "mutual of omaha", "primerica", "ethos", "ladder life", "bestow", "policygenius",
)  # fmt: skip

INSURANCE_TERMS = (
    "insurance", "final expense", "iul", "indexed universal", "annuit", "mortgage protection",
    "life policy", "life policies", "burial",
)  # fmt: skip
AGENCY_TERMS = ("agency", "agencies", "brokerage", "insurance group", "financial group")
AGENT_TERMS = ("agent", "licensed", "producer", "advisor", "adviser", "broker")


@dataclass(frozen=True)
class Classification:
    kind: str | None  # agent | agency | None when the account is not relevant
    is_relevant: bool
    reason: str
    unsure: bool = False  # the rules guessed: worth a second opinion


def _has(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_carrier(name: str) -> bool:
    # Only the channel name counts: agents often write "appointed with Mutual of Omaha" in
    # their bio. A name like "Jane Doe - State Farm Agent" is a person, so agent words win.
    if _has(name, AGENT_TERMS + AGENCY_TERMS):
        return False
    return any(re.search(rf"\b{re.escape(carrier)}\b", name) for carrier in CARRIERS)


def classify_creator(name: str, bio: str | None) -> Classification:
    name_l = name.lower()
    bio_l = (bio or "").lower()
    text = f"{name_l} {bio_l}"

    if _is_carrier(name_l):
        return Classification(None, False, "insurance carrier")
    if not _has(text, INSURANCE_TERMS):
        # "Founder, Legacy Family Life ... hiring agents" has no insurance word but is an agency.
        sounds_like_sales = _has(text, AGENT_TERMS + AGENCY_TERMS)
        return Classification(None, False, "no insurance terms in name or bio", sounds_like_sales)

    if _has(name_l, AGENCY_TERMS):
        return Classification("agency", True, "agency word in name")
    if _has(text, AGENT_TERMS):
        return Classification("agent", True, "agent word in name or bio")
    if _has(bio_l, AGENCY_TERMS):
        return Classification("agency", True, "agency word in bio")
    # Most small channels are personal brands, so "agent" is the safe default.
    return Classification("agent", True, "insurance terms only, assumed agent", unsure=True)
