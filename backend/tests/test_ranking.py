import pytest

from models.schemas import CandidateResult, CriterionResult, EvidenceStatus
from services.ranking import (
    confidence_label,
    criterion_confidence,
    missing_must_haves,
    overall_confidence,
    rank_candidates,
    weighted_total,
)


def crit(name: str, weight: int, score: int, must: bool = False, status: EvidenceStatus = "verified") -> CriterionResult:
    return CriterionResult(
        criterion=name, weight=weight, must_have=must, score=score, evidence="x", reasoning="",
        evidence_status=status, evidence_match=100, confidence=criterion_confidence(status, score),
    )


def cand(cid: str, total: float | None, must_ok: bool = True, conf: float = 0.9, status: str = "done") -> CandidateResult:
    return CandidateResult(id=cid, filename=f"{cid}.pdf", status=status, total_score=total,  # type: ignore[arg-type]
                           must_have_ok=must_ok, confidence=conf)


# ---------- weighted total ----------

def test_weighted_total_perfect_and_zero() -> None:
    assert weighted_total([crit("a", 60, 10), crit("b", 40, 10)]) == 100.0
    assert weighted_total([crit("a", 60, 0), crit("b", 40, 0)]) == 0.0


def test_weighted_total_mixed() -> None:
    # 0.5*7 + 0.3*4 + 0.2*10 = 3.5 + 1.2 + 2.0 = 6.7 -> 67.0
    assert weighted_total([crit("a", 50, 7), crit("b", 30, 4), crit("c", 20, 10)]) == 67.0


def test_weighted_total_rounding_and_empty() -> None:
    # (5*33 + 6*33 + 7*34) / 100 * 10 = 60.1
    assert weighted_total([crit("a", 33, 5), crit("b", 33, 6), crit("c", 34, 7)]) == 60.1
    assert weighted_total([]) == 0.0


# ---------- must-haves ----------

def test_missing_must_haves_threshold() -> None:
    cs = [crit("Python", 40, 5, must=True), crit("AWS", 30, 4, must=True), crit("Go", 30, 0)]
    assert missing_must_haves(cs, min_score=5) == ["AWS"]
    assert missing_must_haves(cs, min_score=6) == ["Python", "AWS"]


# ---------- confidence ----------

@pytest.mark.parametrize(
    "status, score, expected",
    [("verified", 8, 1.0), ("fuzzy", 8, 0.85), ("unverified", 8, 0.3),
     ("not_found", 0, 1.0), ("not_found", 2, 1.0), ("not_found", 6, 0.4)],
)
def test_criterion_confidence(status: EvidenceStatus, score: int, expected: float) -> None:
    assert criterion_confidence(status, score) == expected


def test_overall_confidence_weighted_and_penalised() -> None:
    cs = [crit("a", 70, 8, status="verified"), crit("b", 30, 8, status="unverified")]
    assert overall_confidence(cs) == pytest.approx(0.79)  # 0.7*1 + 0.3*0.3
    assert overall_confidence(cs, penalty=0.8) == pytest.approx(0.63)
    assert confidence_label(0.79) == "medium"
    assert confidence_label(0.8) == "high"
    assert confidence_label(0.54) == "low"


# ---------- ranking ----------

def test_rank_orders_must_have_first_then_score_then_confidence() -> None:
    ranked = rank_candidates([
        cand("low", 40),
        cand("top_but_missing_must", 95, must_ok=False),
        cand("high", 80, conf=0.6),
        cand("high_more_confident", 80, conf=0.95),
        cand("pending", None, status="pending"),
        cand("errored", None, status="error"),
    ])
    assert [c.id for c in ranked] == [
        "high_more_confident", "high", "low", "top_but_missing_must", "pending", "errored",
    ]
    assert [c.rank for c in ranked] == [1, 1, 3, 4, None, None]  # ties share a rank
