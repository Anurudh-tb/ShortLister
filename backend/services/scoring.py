"""Score one resume against a rubric, then verify evidence and compute totals."""
import copy
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from models.schemas import (
    NOT_FOUND,
    CandidateResult,
    CriterionResult,
    CriterionScoreDraft,
    ResumeScoreDraft,
    Rubric,
)
from services.evidence import verify_evidence
from services.llm.base import ChatMessage, LLMProvider
from services.llm.structured import generate_structured
from services.prompts import SCORING_SYSTEM, SCORING_USER
from services.ranking import (
    confidence_label,
    criterion_confidence,
    missing_must_haves,
    overall_confidence,
    weighted_total,
)
from services.tokens import CHARS_PER_TOKEN, estimate_tokens

logger = logging.getLogger(__name__)

TRUNCATION_PENALTY = 0.8
OCR_PENALTY = 0.9


@dataclass
class ResumeInput:
    id: str
    filename: str
    text: str
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)


def criterion_ids(rubric: Rubric) -> list[str]:
    return [f"C{i}" for i in range(1, len(rubric.criteria) + 1)]


def rubric_for_prompt(rubric: Rubric) -> str:
    lines = []
    for cid, c in zip(criterion_ids(rubric), rubric.criteria, strict=True):
        tag = ", MUST-HAVE" if c.must_have else ""
        lines.append(f"{cid}. {c.name} (weight {c.weight}{tag}): {c.description}")
    return "\n".join(lines)


def scoring_schema(rubric: Rubric) -> dict[str, Any]:
    """ResumeScoreDraft schema constrained to this rubric's criterion ids and count."""
    schema = copy.deepcopy(ResumeScoreDraft.model_json_schema())
    ids = criterion_ids(rubric)
    schema["$defs"]["CriterionScoreDraft"]["properties"]["criterion_id"]["enum"] = ids
    schema["properties"]["criteria"].update(minItems=len(ids), maxItems=len(ids))
    schema["required"] = ["candidate_name", "best_fit_role", "criteria", "strengths", "gaps", "summary"]
    return schema


def output_reserve(rubric: Rubric, settings: Settings) -> int:
    return max(settings.output_token_reserve, 150 * len(rubric.criteria) + 400)


def fit_resume(resume_text: str, fixed_prompt: str, rubric: Rubric, settings: Settings) -> tuple[str, str | None]:
    """Trim the resume so the prompt fits NUM_CTX (Ollama would otherwise truncate silently)."""
    budget = settings.num_ctx - output_reserve(rubric, settings) - estimate_tokens(fixed_prompt)
    max_chars = max(0, int(budget * CHARS_PER_TOKEN))
    if len(resume_text) <= max_chars:
        return resume_text, None
    pct = round(100 * max_chars / len(resume_text))
    return resume_text[:max_chars], (
        f"Resume is too long for the context window (NUM_CTX={settings.num_ctx}); only the first ~{pct}% "
        "was scored. Increase NUM_CTX to score the full document."
    )


def _completeness_check(rubric: Rubric) -> Callable[[ResumeScoreDraft], None]:
    expected = set(criterion_ids(rubric))

    def check(draft: ResumeScoreDraft) -> None:
        got = {c.criterion_id.strip().upper() for c in draft.criteria}
        missing = sorted(expected - got)
        if missing:
            raise ValueError(f"criteria missing scores for ids: {', '.join(missing)}")

    return check


def build_candidate_result(
    resume: ResumeInput, rubric: Rubric, draft: ResumeScoreDraft, *, truncated: bool, settings: Settings
) -> CandidateResult:
    by_id: dict[str, CriterionScoreDraft] = {}
    for d in draft.criteria:
        by_id.setdefault(d.criterion_id.strip().upper(), d)

    warnings = list(resume.warnings)
    results: list[CriterionResult] = []
    for cid, c in zip(criterion_ids(rubric), rubric.criteria, strict=True):
        d = by_id.get(cid)
        if d is None:
            warnings.append(f"The model returned no score for '{c.name}'; it was scored 0.")
            results.append(CriterionResult(
                criterion=c.name, weight=c.weight, must_have=c.must_have, score=0, evidence=NOT_FOUND,
                reasoning="Not scored by the model.", evidence_status="not_found", evidence_match=0, confidence=0.0,
            ))
            continue
        # Verify against the full text, so a quote from a truncated tail still counts as genuine.
        check = verify_evidence(d.evidence, resume.text)
        results.append(CriterionResult(
            criterion=c.name,
            weight=c.weight,
            must_have=c.must_have,
            score=d.score,
            evidence=NOT_FOUND if check.status == "not_found" else d.evidence.strip(),
            reasoning=d.reasoning.strip(),
            evidence_status=check.status,
            evidence_match=check.match,
            confidence=criterion_confidence(check.status, d.score),
        ))

    unverified = [r.criterion for r in results if r.evidence_status == "unverified"]
    if unverified:
        warnings.append(f"{len(unverified)} evidence quote(s) could not be found in the resume: {', '.join(unverified)}")

    penalty = (TRUNCATION_PENALTY if truncated else 1.0) * (OCR_PENALTY if resume.ocr_used else 1.0)
    confidence = overall_confidence(results, penalty)
    missing = missing_must_haves(results, settings.must_have_min_score)
    name = (draft.candidate_name or "").strip() or None
    role = (draft.best_fit_role or "").strip()[:120] or None
    return CandidateResult(
        id=resume.id,
        filename=resume.filename,
        status="done",
        candidate_name=name,
        best_fit_role=role,
        total_score=weighted_total(results),
        must_have_ok=not missing,
        must_have_missing=missing,
        confidence=confidence,
        confidence_label=confidence_label(confidence),
        criteria=results,
        strengths=[s.strip() for s in draft.strengths if s.strip()][:6],
        gaps=[g.strip() for g in draft.gaps if g.strip()][:6],
        summary=draft.summary.strip(),
        warnings=warnings,
    )


async def score_resume(
    provider: LLMProvider, settings: Settings, rubric: Rubric, resume: ResumeInput, model: str
) -> CandidateResult:
    rubric_text = rubric_for_prompt(rubric)
    fixed = SCORING_SYSTEM + SCORING_USER.format(rubric=rubric_text, resume_text="")
    resume_text, trunc_warning = fit_resume(resume.text, fixed, rubric, settings)
    if trunc_warning:
        resume = ResumeInput(resume.id, resume.filename, resume.text, resume.ocr_used, [*resume.warnings, trunc_warning])

    logger.info("scoring candidate=%s chars=%d model=%s", resume.id, len(resume_text), model)
    draft = await generate_structured(
        provider,
        [
            ChatMessage("system", SCORING_SYSTEM),
            ChatMessage("user", SCORING_USER.format(rubric=rubric_text, resume_text=resume_text)),
        ],
        ResumeScoreDraft,
        model=model,
        max_retries=settings.llm_max_retries,
        num_ctx=settings.num_ctx,
        json_schema=scoring_schema(rubric),
        check=_completeness_check(rubric),
    )
    return build_candidate_result(resume, rubric, draft, truncated=trunc_warning is not None, settings=settings)
