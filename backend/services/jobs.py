"""In-process background scoring jobs, persisted to the database.

Jobs run as asyncio tasks inside the API process; a restart marks unfinished jobs as failed.
Resume text lives only in memory for the duration of the job unless PERSIST_RESUME_TEXT=true.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.config import Settings
from models.db import CandidateRow, Database, JobRow
from models.schemas import (
    CandidateResult,
    CandidateReview,
    JobDetail,
    JobProgress,
    JobState,
    JobSummary,
    Rubric,
)
from services.cache import LLMCache
from services.llm.base import LLMError, LLMProvider, LLMUnavailableError, ModelNotFoundError
from services.ranking import rank_candidates
from services.rubric import generate_rubric
from services.scoring import ResumeInput, score_resume

logger = logging.getLogger(__name__)

ACTIVE_STATES: tuple[JobState, ...] = ("queued", "generating_rubric", "running")


def _clip(text: str | None, limit: int) -> str | None:
    """Fit a value to its VARCHAR column (MySQL rejects over-long strings in strict mode)."""
    return text[:limit] if text else text


@dataclass
class UploadedResume:
    """A resume after extraction: either text or an extraction error."""

    filename: str
    text: str | None = None
    ocr_used: bool = False
    warnings: list[str] | None = None
    error: str | None = None


class JobManager:
    def __init__(self, db: Database, provider: LLMProvider, settings: Settings) -> None:
        self._db = db
        self._provider = provider
        self._settings = settings
        self._cache = LLMCache(db, settings)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Local LLM servers generally process one request at a time; serialise across jobs.
        self._llm_slot = asyncio.Semaphore(1)

    # ---------- lifecycle ----------

    def recover_interrupted(self) -> int:
        with self._db.session() as s:
            rows = s.scalars(select(JobRow).where(JobRow.status.in_(ACTIVE_STATES))).all()
            for job in rows:
                job.status = "failed"
                job.error = "The server restarted before this job finished. Please re-run it."
                for c in job.candidates:
                    if c.status in ("pending", "scoring"):
                        self._set_candidate(c, status="error", error="Interrupted by server restart")
            return len(rows)

    async def shutdown(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    # ---------- commands ----------

    def create_job(
        self, *, model: str, rubric: Rubric | None, jd_text: str | None, resumes: list[UploadedResume]
    ) -> JobDetail:
        if rubric is None and not jd_text:
            raise ValueError("A rubric or JD text is required")
        job_id = str(uuid.uuid4())
        inputs: list[ResumeInput] = []
        with self._db.session() as s:
            job = JobRow(
                id=job_id, status="queued", model=model,
                job_title=_clip(rubric.job_title, 200) if rubric else None,
                rubric_json=rubric.model_dump_json() if rubric else None,
            )
            for pos, r in enumerate(resumes):
                cid = str(uuid.uuid4())
                result = CandidateResult(
                    id=cid, filename=r.filename,
                    status="error" if r.error else "pending", error=r.error, warnings=r.warnings or [],
                )
                job.candidates.append(CandidateRow(
                    id=cid, position=pos, filename=_clip(r.filename, 300), status=result.status,
                    result_json=result.model_dump_json(),
                    resume_text=r.text if self._settings.persist_resume_text else None,
                ))
                if r.text is not None and not r.error:
                    inputs.append(ResumeInput(cid, r.filename, r.text, r.ocr_used, r.warnings or []))
            s.add(job)

        task = asyncio.create_task(self._run(job_id, model, rubric, jd_text, inputs), name=f"job-{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(job_id, None))
        detail = self.get_job(job_id)
        assert detail is not None
        return detail

    async def delete_job(self, job_id: str) -> bool:
        task = self._tasks.pop(job_id, None)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        with self._db.session() as s:
            job = s.get(JobRow, job_id)
            if job is None:
                return False
            s.delete(job)
        logger.info("deleted job %s", job_id)
        return True

    def review_candidate(self, job_id: str, candidate_id: str, review: CandidateReview) -> CandidateResult | None:
        with self._db.session() as s:
            row = s.get(CandidateRow, candidate_id)
            if row is None or row.job_id != job_id:
                return None
            self._set_candidate(row, **review.model_dump(exclude_none=True))
            return self._to_result(row)

    # ---------- queries ----------

    def get_job(self, job_id: str) -> JobDetail | None:
        with self._db.session() as s:
            job = s.get(JobRow, job_id)
            if job is None:
                return None
            candidates = rank_candidates([self._to_result(c) for c in job.candidates])
            return JobDetail(
                **self._summary(job).model_dump(),
                rubric=Rubric.model_validate_json(job.rubric_json) if job.rubric_json else None,
                candidates=candidates,
            )

    def list_jobs(self) -> list[JobSummary]:
        with self._db.session() as s:
            jobs = s.scalars(select(JobRow).order_by(JobRow.created_at.desc())).all()
            return [self._summary(j) for j in jobs]

    # ---------- worker ----------

    async def _run(
        self, job_id: str, model: str, rubric: Rubric | None, jd_text: str | None, inputs: list[ResumeInput]
    ) -> None:
        try:
            if rubric is None:
                rubric = self._cache.get_rubric(jd_text or "", model)
                if rubric is None:
                    self._update_job(job_id, status="generating_rubric")
                    async with self._llm_slot:
                        rubric, _ = await generate_rubric(self._provider, self._settings, jd_text or "", model)
                    self._cache.put_rubric(jd_text or "", model, rubric)
                self._update_job(job_id, rubric_json=rubric.model_dump_json(), job_title=_clip(rubric.job_title, 200))

            self._update_job(job_id, status="running")
            for resume in inputs:
                if cached := self._cache.get_score(resume, rubric, model):
                    logger.info("candidate %s: reused cached score", resume.id)
                    self._store_result(cached)
                    continue
                self._update_candidate(resume.id, status="scoring")
                try:
                    async with self._llm_slot:
                        result = await score_resume(self._provider, self._settings, rubric, resume, model)
                except (LLMUnavailableError, ModelNotFoundError):
                    raise  # fatal for the whole job
                except LLMError as e:
                    logger.warning("candidate %s failed: %s", resume.id, e)
                    self._update_candidate(resume.id, status="error", error=str(e))
                    continue
                self._cache.put_score(resume, rubric, model, result)
                self._store_result(result)
            self._update_job(job_id, status="completed")
        except asyncio.CancelledError:
            self._update_job(job_id, status="cancelled", error="Cancelled")
            raise
        except LLMError as e:
            logger.error("job %s failed: %s", job_id, e)
            self._update_job(job_id, status="failed", error=str(e))
            self._fail_pending(job_id, str(e))
        except Exception:
            logger.exception("job %s crashed", job_id)
            self._update_job(job_id, status="failed", error="Unexpected server error; see backend logs")
            self._fail_pending(job_id, "Not scored: job failed")

    # ---------- persistence helpers ----------

    def _update_job(self, job_id: str, **fields: object) -> None:
        with self._db.session() as s:
            job = s.get(JobRow, job_id)
            if job is not None:  # may have been deleted mid-run
                for k, v in fields.items():
                    setattr(job, k, v)

    def _update_candidate(self, candidate_id: str, **fields: object) -> None:
        with self._db.session() as s:
            row = s.get(CandidateRow, candidate_id)
            if row is not None:
                self._set_candidate(row, **fields)

    def _store_result(self, result: CandidateResult) -> None:
        with self._db.session() as s:
            row = s.get(CandidateRow, result.id)
            if row is None:
                return
            # Keep any review the recruiter made while this candidate was still being scored.
            current = CandidateResult.model_validate_json(row.result_json)
            result = result.model_copy(update={"decision": current.decision, "notes": current.notes})
            row.status = result.status
            row.total_score = result.total_score
            row.must_have_ok = result.must_have_ok
            row.result_json = result.model_dump_json()

    def _fail_pending(self, job_id: str, error: str) -> None:
        with self._db.session() as s:
            job = s.get(JobRow, job_id)
            for c in job.candidates if job else []:
                if c.status in ("pending", "scoring"):
                    self._set_candidate(c, status="error", error=error)

    @staticmethod
    def _set_candidate(row: CandidateRow, **fields: object) -> None:
        result = CandidateResult.model_validate_json(row.result_json).model_copy(update=fields)
        row.status = result.status
        row.decision = result.decision
        row.result_json = result.model_dump_json()

    @staticmethod
    def _to_result(row: CandidateRow) -> CandidateResult:
        return CandidateResult.model_validate_json(row.result_json).model_copy(
            update={"status": row.status, "decision": row.decision}
        )

    @staticmethod
    def _summary(job: JobRow) -> JobSummary:
        total = len(job.candidates)
        done = sum(1 for c in job.candidates if c.status == "done")
        failed = sum(1 for c in job.candidates if c.status == "error")
        return JobSummary(
            job_id=job.id,
            status=job.status,  # type: ignore[arg-type]
            created_at=job.created_at.isoformat(),
            model=job.model,
            job_title=job.job_title,
            progress=JobProgress(
                total=total, done=done, failed=failed,
                percent=round(100 * (done + failed) / total, 1) if total else 100.0,
            ),
            error=job.error,
        )
