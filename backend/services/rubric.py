"""JD -> weighted rubric generation."""
import math

from app.config import Settings
from models.schemas import WEIGHT_TOTAL, Criterion, DraftCriterion, Rubric, RubricDraft
from services.llm.base import ChatMessage, LLMProvider
from services.llm.structured import generate_structured
from services.prompts import RUBRIC_SYSTEM, RUBRIC_USER
from services.tokens import context_warning


def normalize_weights(raw: list[float], total: int = WEIGHT_TOTAL) -> list[int]:
    """Scale non-negative weights to integers summing exactly to `total` (largest-remainder method)."""
    if not raw:
        return []
    if any(w < 0 or math.isnan(w) for w in raw):
        raise ValueError("weights must be non-negative numbers")
    s = sum(raw)
    scaled = [total / len(raw)] * len(raw) if s == 0 else [w * total / s for w in raw]
    floors = [math.floor(x) for x in scaled]
    remainder = total - sum(floors)
    # Hand out the leftover units to the largest fractional parts (ties -> earlier index).
    order = sorted(range(len(raw)), key=lambda i: (-(scaled[i] - floors[i]), i))
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def draft_to_rubric(draft: RubricDraft) -> Rubric:
    weights = normalize_weights([c.weight for c in draft.criteria])
    criteria: list[Criterion] = []
    seen: dict[str, int] = {}
    for c, w in zip(draft.criteria, weights, strict=True):
        name = c.name.strip()[:110]
        key = name.casefold()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            name = f"{name} ({seen[key]})"
        criteria.append(Criterion(name=name, description=c.description, weight=w, must_have=c.must_have))
    return Rubric(job_title=draft.job_title, criteria=criteria)


async def generate_rubric(
    provider: LLMProvider, settings: Settings, jd_text: str, model: str
) -> tuple[Rubric, list[str]]:
    user = RUBRIC_USER.format(jd_text=jd_text)
    warnings: list[str] = []
    if w := context_warning("The job description", RUBRIC_SYSTEM + user,
                            num_ctx=settings.num_ctx, output_reserve=settings.output_token_reserve):
        warnings.append(w)
    draft = await generate_structured(
        provider,
        [ChatMessage("system", RUBRIC_SYSTEM), ChatMessage("user", user)],
        RubricDraft,
        model=model,
        max_retries=settings.llm_max_retries,
        num_ctx=settings.num_ctx,
    )
    raw_total = sum(c.weight for c in draft.criteria)
    if abs(raw_total - WEIGHT_TOTAL) > 0.5:
        warnings.append(f"Model weights summed to {raw_total:g}; they were rescaled to {WEIGHT_TOTAL}.")
    return draft_to_rubric(draft), warnings
