"""Database cache for LLM output, so re-running the same JD / resumes skips the model.

Keys are SHA-256 hashes of everything that affects the answer (prompt text, model, rubric, resume text),
so editing a prompt or the rubric naturally misses the cache. Resume text itself is never stored here.
"""
import hashlib
import json
import logging

from sqlalchemy.exc import IntegrityError

from app.config import Settings
from models.db import Database, RubricCacheRow, ScoreCacheRow
from models.schemas import CandidateResult, Rubric
from services.prompts import RUBRIC_SYSTEM, SCORING_SYSTEM
from services.scoring import ResumeInput

logger = logging.getLogger(__name__)

# Fields that belong to one job's candidate, not to the (resume, rubric, model) score.
_JOB_FIELDS = {"id", "filename", "decision", "notes", "rank", "cached"}


def sha256(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
        h.update(b"\0")
    return h.hexdigest()


class LLMCache:
    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.llm_cache_enabled

    # ---------- rubric ----------

    @staticmethod
    def rubric_key(jd_text: str, model: str) -> str:
        return sha256(RUBRIC_SYSTEM, model, jd_text.strip())

    def get_rubric(self, jd_text: str, model: str) -> Rubric | None:
        if not self.enabled:
            return None
        with self._db.session() as s:
            row = s.get(RubricCacheRow, self.rubric_key(jd_text, model))
            return Rubric.model_validate_json(row.rubric_json) if row else None

    def put_rubric(self, jd_text: str, model: str, rubric: Rubric) -> None:
        if self.enabled:
            self._put(RubricCacheRow(key=self.rubric_key(jd_text, model), model=model,
                                     rubric_json=rubric.model_dump_json()))

    # ---------- resume scores ----------

    def score_key(self, resume_text: str, rubric: Rubric, model: str) -> str:
        # must_have_min_score and num_ctx change the computed result, so they are part of the key.
        return sha256(SCORING_SYSTEM, model, rubric.model_dump_json(), str(self._settings.must_have_min_score),
                      str(self._settings.num_ctx), sha256(resume_text))

    def get_score(self, resume: ResumeInput, rubric: Rubric, model: str) -> CandidateResult | None:
        if not self.enabled:
            return None
        with self._db.session() as s:
            row = s.get(ScoreCacheRow, self.score_key(resume.text, rubric, model))
            if row is None:
                return None
            data = json.loads(row.result_json)
            return CandidateResult.model_validate({**data, "id": resume.id, "filename": resume.filename, "cached": True})

    def put_score(self, resume: ResumeInput, rubric: Rubric, model: str, result: CandidateResult) -> None:
        if not self.enabled or result.status != "done":
            return
        self._put(ScoreCacheRow(
            key=self.score_key(resume.text, rubric, model),
            resume_hash=sha256(resume.text),
            model=model,
            candidate_name=(result.candidate_name or "")[:200] or None,
            best_fit_role=(result.best_fit_role or "")[:200] or None,
            total_score=result.total_score,
            result_json=result.model_dump_json(exclude=_JOB_FIELDS),
        ))

    def _put(self, row: RubricCacheRow | ScoreCacheRow) -> None:
        try:
            with self._db.session() as s:
                s.merge(row)
        except IntegrityError:
            # Another job stored the same key concurrently; either copy is fine.
            logger.debug("cache key %s already stored", row.key)
