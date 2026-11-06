"""Deterministic offline provider (LLM_PROVIDER=mock) for demos and development without Ollama.

It produces plausible-looking output with simple heuristics; it is NOT an evaluator.
"""
import json
import re
from typing import Any

from models.schemas import ModelInfo
from services.llm.base import ChatMessage, LLMProvider

_BULLET_RE = re.compile(r"^\s*(?:[-*•●]|\d+[.)])\s+(.+)$")
_MUST_RE = re.compile(r"\b(must|required|requirement|minimum|at least|mandatory)\b", re.IGNORECASE)
_JD_RE = re.compile(r"<job_description>(.*?)</job_description>", re.DOTALL)


class MockProvider(LLMProvider):
    name = "mock"

    async def chat_json(
        self,
        messages: list[ChatMessage],
        json_schema: dict[str, Any],
        *,
        model: str,
        temperature: float = 0.0,
        num_ctx: int | None = None,
    ) -> str:
        title = json_schema.get("title")
        user_text = "\n".join(m.content for m in messages if m.role == "user")
        if title == "RubricDraft":
            return json.dumps(_mock_rubric(user_text))
        if title == "ResumeScoreDraft":
            return json.dumps(_mock_score(user_text))
        raise NotImplementedError(f"MockProvider has no canned response for schema {title!r}")

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name="mock-model", parameter_size="n/a", family="mock")]


_RUBRIC_LINE_RE = re.compile(r"^(C\d+)\. (.+?) \(weight \d+(?:, MUST-HAVE)?\): (.*)$")
_RESUME_RE = re.compile(r"<resume>\n(.*?)\n</resume>", re.DOTALL)
_WORD_RE = re.compile(r"[a-z][a-z0-9+#.]{2,}")
_STOP = {"and", "the", "with", "for", "experience", "years", "strong", "must", "have", "required",
         "professional", "familiarity", "ability", "good", "knowledge", "working", "production"}


def _words(text: str) -> set[str]:
    return {w.rstrip(".") for w in _WORD_RE.findall(text.lower())} - _STOP


def _mock_score(user_text: str) -> dict[str, Any]:
    """Keyword-overlap scoring: picks the resume line sharing most words with each criterion."""
    rubric = [m.groups() for ln in user_text.splitlines() if (m := _RUBRIC_LINE_RE.match(ln))]
    rm = _RESUME_RE.search(user_text)
    lines = [ln.strip() for ln in (rm.group(1) if rm else "").splitlines() if ln.strip()]
    criteria, strengths, gaps = [], [], []
    for cid, name, desc in rubric:
        keys = _words(f"{name} {desc}")
        best, overlap = max(((ln, len(keys & _words(ln))) for ln in lines), key=lambda t: t[1], default=("", 0))
        score = min(10, 3 * overlap) if overlap else 0
        criteria.append({
            "criterion_id": cid, "score": score,
            "evidence": best if overlap else "not found",
            "reasoning": f"Mock: {overlap} keyword(s) from the criterion appear in this line." if overlap
            else "Mock: no keywords from the criterion found.",
        })
        (strengths if score >= 6 else gaps).append(name)
    return {
        "candidate_name": lines[0][:80] if lines else None,
        "best_fit_role": lines[1][:80] if len(lines) > 1 else None,
        "criteria": criteria, "strengths": strengths[:4], "gaps": gaps[:4],
        "summary": "Mock assessment based on keyword overlap (LLM_PROVIDER=mock).",
    }


def _mock_rubric(user_text: str) -> dict[str, Any]:
    m = _JD_RE.search(user_text)
    jd = m.group(1) if m else user_text
    lines = [ln.strip() for ln in jd.splitlines() if ln.strip()]
    bullets = [b.group(1).strip() for ln in lines if (b := _BULLET_RE.match(ln))]
    criteria: list[dict[str, Any]] = []
    seen: set[str] = set()
    for b in bullets:
        name = " ".join(b.split()[:6]).rstrip(".,;:")
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        criteria.append({"name": name, "description": b, "weight": 10, "must_have": bool(_MUST_RE.search(b))})
        if len(criteria) == 8:
            break
    if not criteria:
        criteria = [
            {"name": "Relevant experience", "description": "Experience matching the role", "weight": 40, "must_have": True},
            {"name": "Technical skills", "description": "Skills listed in the JD", "weight": 40, "must_have": False},
            {"name": "Communication", "description": "Written/verbal communication", "weight": 20, "must_have": False},
        ]
    return {"job_title": lines[0][:120] if lines else None, "criteria": criteria}
