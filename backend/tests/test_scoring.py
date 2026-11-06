from typing import Any

import pytest

from app.config import Settings
from models.schemas import Criterion, Rubric
from services.llm.base import ChatMessage, LLMOutputError
from services.scoring import ResumeInput, fit_resume, score_resume, scoring_schema
from tests.conftest import ScriptedProvider

SETTINGS = Settings(_env_file=None, llm_provider="mock", llm_max_retries=1, must_have_min_score=5)
RUBRIC = Rubric(job_title="Backend Engineer", criteria=[
    Criterion(name="Python", description="Production Python", weight=50, must_have=True),
    Criterion(name="Kubernetes", description="Running k8s in prod", weight=30),
    Criterion(name="Leadership", description="Led a team", weight=20, must_have=True),
])
RESUME = ResumeInput(
    id="c1", filename="jane.pdf",
    text="Jane Doe\nBuilt REST APIs in Python and FastAPI for 6 years.\nRan workloads on Kubernetes (EKS).",
)


def draft(**overrides: Any) -> dict[str, Any]:
    base = {
        "candidate_name": "Jane Doe",
        "criteria": [
            {"criterion_id": "C1", "score": 9, "evidence": "Built REST APIs in Python and FastAPI for 6 years.",
             "reasoning": "Six years of Python."},
            {"criterion_id": "C2", "score": 7, "evidence": "Managed 300-node Kubernetes clusters",  # fabricated
             "reasoning": "Kubernetes experience."},
            {"criterion_id": "C3", "score": 0, "evidence": "not found", "reasoning": "No leadership mentioned."},
        ],
        "strengths": ["Python depth", " "],
        "gaps": ["No leadership evidence"],
        "summary": "Strong Python engineer.",
    }
    return base | overrides


async def test_score_resume_end_to_end() -> None:
    result = await score_resume(ScriptedProvider([draft()]), SETTINGS, RUBRIC, RESUME, "fake")
    c1, c2, c3 = result.criteria
    assert (c1.evidence_status, c2.evidence_status, c3.evidence_status) == ("verified", "unverified", "not_found")
    assert c2.confidence == 0.3
    # 0.5*9 + 0.3*7 + 0.2*0 = 6.6 -> 66.0
    assert result.total_score == 66.0
    assert result.must_have_ok is False and result.must_have_missing == ["Leadership"]
    # confidence = 0.5*1 + 0.3*0.3 + 0.2*1 = 0.79
    assert result.confidence == pytest.approx(0.79) and result.confidence_label == "medium"
    assert result.strengths == ["Python depth"]
    assert any("could not be found" in w for w in result.warnings)


async def test_missing_criterion_triggers_repair() -> None:
    incomplete = draft(criteria=draft()["criteria"][:2])
    provider = ScriptedProvider([incomplete, draft()])
    result = await score_resume(provider, SETTINGS, RUBRIC, RESUME, "fake")
    assert len(result.criteria) == 3
    assert "C3" in provider.calls[1][-1].content


async def test_persistent_invalid_output_raises() -> None:
    provider = ScriptedProvider(["not json", draft(criteria=[{"criterion_id": "C1", "score": 42}])])
    with pytest.raises(LLMOutputError):
        await score_resume(provider, SETTINGS, RUBRIC, RESUME, "fake")


async def test_prompt_contains_rubric_ids_fairness_and_resume() -> None:
    provider = ScriptedProvider([draft()])
    await score_resume(provider, SETTINGS, RUBRIC, RESUME, "fake")
    system, user = provider.calls[0]
    assert "Fairness rules" in system.content and "untrusted data" in system.content
    assert "C1. Python (weight 50, MUST-HAVE): Production Python" in user.content
    assert "<resume>\nJane Doe" in user.content


def test_scoring_schema_constrains_ids() -> None:
    schema = scoring_schema(RUBRIC)
    assert schema["$defs"]["CriterionScoreDraft"]["properties"]["criterion_id"]["enum"] == ["C1", "C2", "C3"]
    assert schema["properties"]["criteria"]["minItems"] == 3 == schema["properties"]["criteria"]["maxItems"]


async def test_long_resume_is_truncated_with_warning_and_lower_confidence() -> None:
    small_ctx = Settings(_env_file=None, llm_provider="mock", num_ctx=2048, output_token_reserve=256)
    long_resume = ResumeInput("c2", "long.txt", RESUME.text + "\n" + "Filler line about hobbies. " * 2000)
    text, warning = fit_resume(long_resume.text, "system prompt", RUBRIC, small_ctx)
    assert len(text) < len(long_resume.text) and warning and "NUM_CTX" in warning

    def respond(messages: list[ChatMessage]) -> str:
        import json
        assert len(messages[1].content) < len(long_resume.text)
        return json.dumps(draft(criteria=[{**c, "evidence": "not found", "score": 0} for c in draft()["criteria"]]))

    result = await score_resume(ScriptedProvider([respond]), small_ctx, RUBRIC, long_resume, "fake")
    assert any("context window" in w for w in result.warnings)
    assert result.confidence == pytest.approx(0.8)  # all consistent not_found (1.0) * truncation penalty 0.8
