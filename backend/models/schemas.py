"""Pydantic models shared by the API and services.

These mirror the TypeScript interfaces in the Angular ApiService.
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

WEIGHT_TOTAL = 100


# ---------- Rubric ----------

class Criterion(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    weight: int = Field(ge=0, le=WEIGHT_TOTAL)
    must_have: bool = False

    @field_validator("name", "description")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class Rubric(BaseModel):
    """A validated rubric: weights are integers that sum to exactly 100."""

    job_title: str | None = None
    criteria: list[Criterion] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _check(self) -> "Rubric":
        total = sum(c.weight for c in self.criteria)
        if total != WEIGHT_TOTAL:
            raise ValueError(f"Criterion weights must sum to {WEIGHT_TOTAL} (got {total})")
        names = [c.name.casefold() for c in self.criteria]
        if len(names) != len(set(names)):
            raise ValueError("Criterion names must be unique")
        return self


class DraftCriterion(BaseModel):
    """Lenient criterion shape the LLM fills in; weights are normalised afterwards."""

    # No defaults: every field must be present in the model's JSON (an omitted field triggers a repair retry).
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=3)
    weight: float = Field(ge=0)
    must_have: bool


class RubricDraft(BaseModel):
    """Structured output requested from the LLM for rubric generation."""

    job_title: str | None = None
    criteria: list[DraftCriterion] = Field(min_length=1, max_length=20)


class RubricResponse(BaseModel):
    rubric: Rubric
    jd_text: str
    model: str
    warnings: list[str] = []


# ---------- Scoring (LLM output) ----------

NOT_FOUND = "not found"


class CriterionScoreDraft(BaseModel):
    criterion_id: str = Field(description="The id of the rubric criterion, e.g. C1")
    score: int = Field(ge=0, le=10)
    evidence: str = Field(description='Exact verbatim quote from the resume, or "not found"')
    reasoning: str


class ResumeScoreDraft(BaseModel):
    """Structured output requested from the LLM for one resume."""

    candidate_name: str | None = None
    best_fit_role: str | None = Field(default=None, description="Job title this resume is best suited for")
    criteria: list[CriterionScoreDraft]
    strengths: list[str] = []
    gaps: list[str] = []
    summary: str = ""


# ---------- Scoring (results) ----------

EvidenceStatus = Literal["verified", "fuzzy", "unverified", "not_found"]
ConfidenceLabel = Literal["high", "medium", "low"]
CandidateStatus = Literal["pending", "scoring", "done", "error"]
JobState = Literal["queued", "generating_rubric", "running", "completed", "failed", "cancelled"]
Decision = Literal["pending", "shortlisted", "rejected"]


class CriterionResult(BaseModel):
    criterion: str
    weight: int
    must_have: bool
    score: int = Field(ge=0, le=10)
    evidence: str
    reasoning: str
    evidence_status: EvidenceStatus
    evidence_match: float = Field(ge=0, le=100, description="Best fuzzy match ratio of the quote in the resume")
    confidence: float = Field(ge=0, le=1)


class CandidateResult(BaseModel):
    id: str
    filename: str
    status: CandidateStatus
    error: str | None = None
    candidate_name: str | None = None
    best_fit_role: str | None = None
    rank: int | None = None
    total_score: float | None = Field(default=None, ge=0, le=100)
    must_have_ok: bool | None = None
    must_have_missing: list[str] = []
    confidence: float | None = None
    confidence_label: ConfidenceLabel | None = None
    criteria: list[CriterionResult] = []
    strengths: list[str] = []
    gaps: list[str] = []
    summary: str = ""
    warnings: list[str] = []
    decision: Decision = "pending"
    notes: str = ""
    # True when the result was reused from the score cache instead of calling the LLM.
    cached: bool = False


class JobProgress(BaseModel):
    total: int
    done: int
    failed: int
    percent: float


class JobSummary(BaseModel):
    job_id: str
    status: JobState
    created_at: str
    model: str
    job_title: str | None = None
    progress: JobProgress
    error: str | None = None


class JobDetail(JobSummary):
    rubric: Rubric | None = None
    candidates: list[CandidateResult]


class ScoreJobCreated(BaseModel):
    job_id: str
    status: JobState
    candidates: list[CandidateResult]


class CandidateReview(BaseModel):
    """Recruiter's manual review; omitted fields are left unchanged."""

    decision: Decision | None = None
    notes: str | None = Field(default=None, max_length=4000)


# ---------- LLM / system ----------

class ModelInfo(BaseModel):
    name: str
    size_bytes: int | None = None
    parameter_size: str | None = None
    family: str | None = None


class PublicConfig(BaseModel):
    """Non-secret settings the UI needs for validation and display."""

    provider: str
    default_model: str
    num_ctx: int
    max_file_mb: float
    max_resumes_per_job: int
    must_have_min_score: int
    persist_resume_text: bool
    ocr_enabled: bool
    priority_weight: int


class ModelsResponse(BaseModel):
    provider: str
    default_model: str
    models: list[ModelInfo]


class ErrorResponse(BaseModel):
    code: str
    detail: str


FileType = Literal["pdf", "docx", "txt"]
