"""Provider-agnostic LLM interface.

To add a provider (e.g. the Claude API), implement LLMProvider and register it in
services/llm/factory.py; select it via LLM_MODE / LLM_PROVIDER.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from models.schemas import ModelInfo


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(Exception):
    """Base class for provider failures."""

    code = "llm_error"


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"


class LLMTimeoutError(LLMError):
    """One request took longer than LLM_TIMEOUT_S. The provider is up, so a job skips just that item."""

    code = "llm_timeout"


class ModelNotFoundError(LLMError):
    code = "model_not_found"


class LLMOutputError(LLMError):
    """The model kept returning output that failed JSON/schema validation."""

    code = "llm_invalid_output"


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def chat_json(
        self,
        messages: list[ChatMessage],
        json_schema: dict[str, Any],
        *,
        model: str,
        temperature: float = 0.0,
        num_ctx: int | None = None,
    ) -> str:
        """Return the raw text of a completion constrained to `json_schema`."""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return the models available to this provider."""

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        return None
