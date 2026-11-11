from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.deps import get_job_manager
from models.schemas import CandidateResult, CandidateReview, JobDetail, JobSummary, Rubric, ScoreJobCreated
from routers.rubric import read_jd
from services.rubric import PRIORITY_MAX_CHARS
from services.extraction import ExtractionError, extract_text
from services.jobs import JobManager, UploadedResume

router = APIRouter(prefix="/api", tags=["jobs"])


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "not_found", "detail": f"{what} not found"})


@router.post("/score", response_model=ScoreJobCreated, status_code=202)
async def start_scoring(
    resumes: Annotated[list[UploadFile], File(description="Resume files (PDF, DOCX, TXT)")],
    rubric: Annotated[str | None, Form(description="Rubric JSON; if omitted it is generated from the JD")] = None,
    jd_text: Annotated[str | None, Form()] = None,
    jd_file: Annotated[UploadFile | None, File()] = None,
    # Recruiter's own skill/expertise prompt; scored as one extra criterion worth PRIORITY_WEIGHT % of the total.
    priority: Annotated[str | None, Form(max_length=PRIORITY_MAX_CHARS)] = None,
    model: Annotated[str | None, Form()] = None,
    settings: Settings = Depends(get_settings),
    manager: JobManager = Depends(get_job_manager),
) -> ScoreJobCreated:
    parsed_rubric: Rubric | None = None
    jd: str | None = None
    if rubric:
        try:
            parsed_rubric = Rubric.model_validate_json(rubric)
        except ValidationError as e:
            msg = "; ".join(err["msg"] for err in e.errors()[:5])
            raise HTTPException(422, detail={"code": "invalid_rubric", "detail": msg}) from e
    else:
        jd = await read_jd(jd_text, jd_file, settings)

    if not resumes:
        raise HTTPException(422, detail={"code": "no_resumes", "detail": "Upload at least one resume"})
    if len(resumes) > settings.max_resumes_per_job:
        raise HTTPException(422, detail={
            "code": "too_many_resumes",
            "detail": f"At most {settings.max_resumes_per_job} resumes per job (got {len(resumes)})",
        })

    uploaded: list[UploadedResume] = []
    for f in resumes:
        name = f.filename or "resume"
        data = await f.read(settings.max_file_bytes + 1)
        try:
            doc = extract_text(name, data, max_bytes=settings.max_file_bytes, ocr_enabled=settings.ocr_enabled)
            uploaded.append(UploadedResume(name, doc.text, doc.ocr_used, doc.warnings))
        except ExtractionError as e:
            uploaded.append(UploadedResume(name, error=str(e)))

    job = manager.create_job(model=model or settings.active_model, rubric=parsed_rubric, jd_text=jd,
                             priority=(priority or "").strip() or None, resumes=uploaded)
    return ScoreJobCreated(job_id=job.job_id, status=job.status, candidates=job.candidates)


@router.get("/jobs", response_model=list[JobSummary])
async def list_jobs(manager: JobManager = Depends(get_job_manager)) -> list[JobSummary]:
    return manager.list_jobs()


@router.get("/jobs/{job_id}", response_model=JobDetail)
async def get_job(job_id: str, manager: JobManager = Depends(get_job_manager)) -> JobDetail:
    job = manager.get_job(job_id)
    if job is None:
        raise _not_found("Job")
    return job


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, manager: JobManager = Depends(get_job_manager)) -> Response:
    if not await manager.delete_job(job_id):
        raise _not_found("Job")
    return Response(status_code=204)


@router.patch("/jobs/{job_id}/candidates/{candidate_id}", response_model=CandidateResult)
async def review_candidate(
    job_id: str, candidate_id: str, body: CandidateReview, manager: JobManager = Depends(get_job_manager)
) -> CandidateResult:
    result = manager.review_candidate(job_id, candidate_id, body)
    if result is None:
        raise _not_found("Candidate")
    return result
