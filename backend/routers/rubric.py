from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import Settings, get_settings
from app.deps import get_provider
from models.schemas import RubricResponse
from services.extraction import extract_text
from services.llm.base import LLMProvider
from services.rubric import generate_rubric

router = APIRouter(prefix="/api", tags=["rubric"])


async def read_jd(jd_text: str | None, jd_file: UploadFile | None, settings: Settings) -> str:
    """Resolve the JD from an uploaded file and/or pasted text.

    With both, the text is treated as extra criteria the recruiter typed under the uploaded JD.
    """
    text = (jd_text or "").strip()
    if jd_file is not None:
        data = await jd_file.read(settings.max_file_bytes + 1)
        file_text = extract_text(jd_file.filename or "jd", data, max_bytes=settings.max_file_bytes,
                                 ocr_enabled=settings.ocr_enabled).text.strip()
        return f"{file_text}\n\nAdditional criteria from the recruiter:\n{text}" if text else file_text
    if text:
        return text
    raise HTTPException(status_code=422, detail={"code": "jd_missing", "detail": "Provide jd_text or jd_file"})


@router.post("/rubric", response_model=RubricResponse)
async def create_rubric(
    jd_text: Annotated[str | None, Form()] = None,
    jd_file: Annotated[UploadFile | None, File()] = None,
    model: Annotated[str | None, Form()] = None,
    settings: Settings = Depends(get_settings),
    provider: LLMProvider = Depends(get_provider),
) -> RubricResponse:
    text = await read_jd(jd_text, jd_file, settings)
    model_name = model or settings.active_model
    rubric, warnings = await generate_rubric(provider, settings, text, model_name)
    return RubricResponse(rubric=rubric, jd_text=text, model=model_name, warnings=warnings)
