"""FastAPI application entrypoint: `uvicorn app.main:app --reload` (run from backend/)."""
import logging
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.deps import RENEWED_TOKEN_EXPIRES_HEADER, RENEWED_TOKEN_HEADER, require_user
from models.db import Database
from routers import auth, jobs, llm, rubric
from services.extraction import ExtractionError, FileTooLargeError, UnsupportedFileTypeError
from services.jobs import JobManager
from services.llm.base import LLMError, LLMOutputError, LLMTimeoutError, LLMUnavailableError, ModelNotFoundError
from services.llm.factory import build_provider
from services.auth_tokens import TokenService
from services.rate_limit import AuthRateLimiter, RateLimited

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("shortlister")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.provider = build_provider(settings)
    app.state.tokens = TokenService(settings)
    app.state.rate_limiter = AuthRateLimiter(ip_per_minute=settings.auth_rate_limit_per_minute,
                                             max_failures=settings.login_max_failures,
                                             lockout_minutes=settings.login_lockout_minutes)
    app.state.db = Database(settings.database_url)
    app.state.jobs = JobManager(app.state.db, app.state.provider, settings)
    if n := app.state.jobs.recover_interrupted():
        logger.warning("marked %d interrupted job(s) as failed", n)
    logger.info("LLM provider=%s model=%s num_ctx=%d", settings.effective_provider, settings.active_model, settings.num_ctx)
    yield
    await app.state.jobs.shutdown()
    await app.state.provider.aclose()
    app.state.db.dispose()


app = FastAPI(title="Resume Shortlisting Assistant", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[RENEWED_TOKEN_HEADER, RENEWED_TOKEN_EXPIRES_HEADER, "Retry-After"],
)
app.include_router(auth.router)
# Everything else needs a sign-in token (see app.deps.require_user).
for _router in (rubric.router, llm.router, jobs.router):
    app.include_router(_router, dependencies=[Depends(require_user)])


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": {"code": code, "detail": detail}})


@app.exception_handler(ExtractionError)
async def _extraction_error(_: Request, exc: ExtractionError) -> JSONResponse:
    status = 413 if isinstance(exc, FileTooLargeError) else 415 if isinstance(exc, UnsupportedFileTypeError) else 422
    return _error(status, exc.code, str(exc))


@app.exception_handler(RateLimited)
async def _rate_limited(_: Request, exc: RateLimited) -> JSONResponse:
    minutes = math.ceil(exc.retry_after / 60)
    wait = f"{exc.retry_after} seconds" if exc.retry_after < 60 else f"{minutes} minute{'s' if minutes > 1 else ''}"
    response = _error(429, "too_many_requests", f"Too many attempts. Try again in {wait}.")
    response.headers["Retry-After"] = str(exc.retry_after)
    return response


@app.exception_handler(LLMError)
async def _llm_error(_: Request, exc: LLMError) -> JSONResponse:
    status = {LLMUnavailableError: 503, LLMTimeoutError: 504, ModelNotFoundError: 400, LLMOutputError: 502}.get(type(exc), 502)
    return _error(status, exc.code, str(exc))


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "provider": settings.effective_provider, "model": settings.active_model}
