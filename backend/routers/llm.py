from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.deps import get_provider
from models.schemas import ModelsResponse, PublicConfig
from services.defaults import DefaultsError, load_defaults
from services.llm.base import LLMProvider

router = APIRouter(prefix="/api", tags=["llm"])


@router.get("/models", response_model=ModelsResponse)
async def list_models(
    settings: Settings = Depends(get_settings),
    provider: LLMProvider = Depends(get_provider),
) -> ModelsResponse:
    return ModelsResponse(provider=provider.name, default_model=settings.active_model,
                          models=await provider.list_models())


@router.get("/config", response_model=PublicConfig)
async def public_config(settings: Settings = Depends(get_settings)) -> PublicConfig:
    try:
        defaults = load_defaults(settings)
    except DefaultsError:
        defaults = None
    return PublicConfig(
        default_jd=defaults.jd_text if defaults else None,
        default_criteria=defaults.rubric if defaults else None,
        provider=settings.effective_provider,
        default_model=settings.active_model,
        num_ctx=settings.num_ctx,
        max_file_mb=settings.max_file_mb,
        max_resumes_per_job=settings.max_resumes_per_job,
        must_have_min_score=settings.must_have_min_score,
        persist_resume_text=settings.persist_resume_text,
        ocr_enabled=settings.ocr_enabled,
    )
