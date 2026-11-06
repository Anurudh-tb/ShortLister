"""Structured-output helper: JSON parse + Pydantic validation + repair-prompt retries."""
import json
import logging
import re
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from services.llm.base import ChatMessage, LLMOutputError, LLMProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)

REPAIR_PROMPT = (
    "Your previous reply was not valid for the required JSON schema.\n"
    "Error: {error}\n"
    "Reply again with ONLY a single JSON object that matches the schema exactly. "
    "No markdown, no commentary."
)


def parse_json_object(raw: str) -> object:
    """Parse model output, tolerating markdown fences and leading/trailing chatter."""
    text = _FENCE_RE.sub("", raw.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def generate_structured(
    provider: LLMProvider,
    messages: list[ChatMessage],
    output_model: type[T],
    *,
    model: str,
    max_retries: int,
    num_ctx: int | None = None,
    json_schema: dict[str, Any] | None = None,
    check: Callable[[T], None] | None = None,
) -> T:
    """Call the provider and validate the result, re-prompting on invalid output.

    `json_schema` overrides the schema sent to the model (e.g. to add enums); `check` adds
    semantic validation and should raise ValueError to trigger a repair attempt.
    """
    schema = json_schema or output_model.model_json_schema()
    convo = list(messages)
    last_error = "unknown"
    for attempt in range(max_retries + 1):
        raw = await provider.chat_json(convo, schema, model=model, temperature=0.0, num_ctx=num_ctx)
        try:
            result = output_model.model_validate(parse_json_object(raw))
            if check is not None:
                check(result)
            return result
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_error = _short_error(e)
            logger.warning(
                "invalid structured output (attempt %d/%d, %s): %s",
                attempt + 1, max_retries + 1, output_model.__name__, last_error,
            )
            convo = [
                *messages,
                ChatMessage("assistant", raw[:4000]),
                ChatMessage("user", REPAIR_PROMPT.format(error=last_error)),
            ]
    raise LLMOutputError(
        f"Model returned invalid {output_model.__name__} after {max_retries + 1} attempts: {last_error}"
    )


def _short_error(e: Exception) -> str:
    if isinstance(e, ValidationError):
        parts = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()[:5]]
        return "; ".join(parts)
    return str(e)[:300]
