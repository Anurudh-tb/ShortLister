"""Pure ranking math: weighted totals, must-have checks, confidence, and ordering."""
from collections.abc import Sequence

from models.schemas import CandidateResult, ConfidenceLabel, CriterionResult, EvidenceStatus

# Confidence in a criterion's score given how its evidence checked out.
EVIDENCE_CONFIDENCE: dict[EvidenceStatus, float] = {
    "verified": 1.0,
    "fuzzy": 0.85,
    "unverified": 0.3,
    "not_found": 1.0,  # adjusted in criterion_confidence when a high score has no evidence
}
# A score above this with no evidence is an internal contradiction in the model's answer.
NO_EVIDENCE_MAX_CONSISTENT_SCORE = 2


def criterion_confidence(status: EvidenceStatus, score: int) -> float:
    if status == "not_found" and score > NO_EVIDENCE_MAX_CONSISTENT_SCORE:
        return 0.4
    return EVIDENCE_CONFIDENCE[status]


def weighted_total(criteria: Sequence[CriterionResult]) -> float:
    """Weighted score on a 0-100 scale (weights sum to 100, scores are 0-10)."""
    total_weight = sum(c.weight for c in criteria)
    if total_weight == 0:
        return 0.0
    raw = sum(c.score * c.weight for c in criteria) / total_weight * 10
    return round(raw, 1)


def missing_must_haves(criteria: Sequence[CriterionResult], min_score: int) -> list[str]:
    return [c.criterion for c in criteria if c.must_have and c.score < min_score]


def overall_confidence(criteria: Sequence[CriterionResult], penalty: float = 1.0) -> float:
    """Weight-averaged criterion confidence, scaled by a document-level penalty (OCR, truncation)."""
    total_weight = sum(c.weight for c in criteria)
    if total_weight == 0:
        return 0.0
    avg = sum(c.confidence * c.weight for c in criteria) / total_weight
    return round(max(0.0, min(1.0, avg * penalty)), 2)


def confidence_label(confidence: float) -> ConfidenceLabel:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def rank_candidates(candidates: Sequence[CandidateResult]) -> list[CandidateResult]:
    """Order scored candidates: must-haves met first, then total score, then confidence.

    Candidates with ties get the same rank (1, 2, 2, 4). Unscored candidates keep rank None
    and are listed last in their original order.
    """
    scored = [c for c in candidates if c.status == "done" and c.total_score is not None]
    scored_ids = {c.id for c in scored}
    others = [c for c in candidates if c.id not in scored_ids]

    def key(c: CandidateResult) -> tuple[bool, float, float]:
        return (not c.must_have_ok, -(c.total_score or 0.0), -(c.confidence or 0.0))

    ordered = sorted(scored, key=key)
    out: list[CandidateResult] = []
    prev_key: tuple[bool, float] | None = None
    rank = 0
    for i, c in enumerate(ordered, start=1):
        tie_key = (bool(c.must_have_ok), c.total_score or 0.0)
        if tie_key != prev_key:
            rank = i
            prev_key = tie_key
        out.append(c.model_copy(update={"rank": rank}))
    out.extend(c.model_copy(update={"rank": None}) for c in others)
    return out
