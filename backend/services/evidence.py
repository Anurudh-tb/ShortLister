"""Verify that LLM-quoted evidence actually appears in the resume text."""
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from models.schemas import NOT_FOUND, EvidenceStatus

# partial_ratio >= this counts as a fuzzy (near-verbatim) match.
FUZZY_THRESHOLD = 90.0
# Quotes shorter than this (after normalisation) must match exactly; fuzzy matching them is meaningless.
MIN_FUZZY_LEN = 12

_NOT_FOUND_VALUES = {"", NOT_FOUND, "n/a", "na", "none", "null", "-", "not mentioned", "no evidence"}
_ELLIPSIS_RE = re.compile(r"\s*(?:\.{3,}|…)\s*")
_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "•": " ", "●": " ", "·": " ",
})


@dataclass(frozen=True)
class EvidenceCheck:
    status: EvidenceStatus
    match: float  # 0-100


def normalize_for_match(text: str) -> str:
    """Case-fold, unify quotes/dashes/bullets, and collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).casefold()
    return re.sub(r"\s+", " ", text).strip()


def is_not_found(evidence: str) -> bool:
    return normalize_for_match(evidence).strip(" .\"'") in _NOT_FOUND_VALUES


def verify_evidence(evidence: str, resume_text: str) -> EvidenceCheck:
    """Classify a quote as verified (exact), fuzzy (near-exact), unverified, or not_found.

    Quotes the model stitched together with an ellipsis are split and every fragment must match;
    the weakest fragment decides the result.
    """
    if is_not_found(evidence):
        return EvidenceCheck("not_found", 0.0)
    haystack = normalize_for_match(resume_text)
    quote = normalize_for_match(evidence).strip("\"' ")
    fragments = [f.strip("\"' ") for f in _ELLIPSIS_RE.split(quote)]
    fragments = [f for f in fragments if f] or [quote]

    worst: EvidenceCheck | None = None
    for frag in fragments:
        check = _verify_fragment(frag, haystack)
        if worst is None or _RANK[check.status] > _RANK[worst.status] or (
            check.status == worst.status and check.match < worst.match
        ):
            worst = check
    assert worst is not None
    return worst


_RANK: dict[EvidenceStatus, int] = {"verified": 0, "fuzzy": 1, "unverified": 2, "not_found": 3}


def _verify_fragment(fragment: str, haystack: str) -> EvidenceCheck:
    if fragment in haystack:
        return EvidenceCheck("verified", 100.0)
    if len(fragment) < MIN_FUZZY_LEN:
        return EvidenceCheck("unverified", 0.0)
    ratio = fuzz.partial_ratio(fragment, haystack) if len(fragment) <= len(haystack) else 0.0
    return EvidenceCheck("fuzzy" if ratio >= FUZZY_THRESHOLD else "unverified", round(ratio, 1))
