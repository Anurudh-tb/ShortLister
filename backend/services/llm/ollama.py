"""Ollama implementation of LLMProvider (uses /api/chat with structured `format`)."""
import logging
from typing import Any

import httpx

from models.schemas import ModelInfo
from services.llm.base import (
    ChatMessage,
    LLMError,
    LLMProvider,
    LLMUnavailableError,
    ModelNotFoundError,
)

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, host: str, timeout_s: float, default_num_ctx: int) -> None:
        self._host = host.rstrip("/")
        self._default_num_ctx = default_num_ctx
        self._client = httpx.AsyncClient(base_url=self._host, timeout=httpx.Timeout(timeout_s, connect=5.0))

    async def chat_json(
        self,
        messages: list[ChatMessage],
        json_schema: dict[str, Any],
        *,
        model: str,
        temperature: float = 0.0,
        num_ctx: int | None = None,
    ) -> str:
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "format": json_schema,
            "options": {"temperature": temperature, "num_ctx": num_ctx or self._default_num_ctx, "seed": 42},
        }
        data = await self._request("POST", "/api/chat", json=payload, model=model)
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str):
            raise LLMError("Ollama response did not contain message content")
        logger.debug("ollama chat ok model=%s eval_count=%s", model, data.get("eval_count"))
        return content

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request("GET", "/api/tags")
        out: list[ModelInfo] = []
        for m in data.get("models", []):
            details = m.get("details") or {}
            out.append(
                ModelInfo(
                    name=m.get("name") or m.get("model", "?"),
                    size_bytes=m.get("size"),
                    parameter_size=details.get("parameter_size"),
                    family=details.get("family"),
                )
            )
        return sorted(out, key=lambda m: m.name)

    async def _request(self, method: str, path: str, *, json: Any = None, model: str | None = None) -> dict[str, Any]:
        try:
            resp = await self._client.request(method, path, json=json)
        except httpx.ConnectError as e:
            raise LLMUnavailableError(
                f"Cannot reach Ollama at {self._host}. Is `ollama serve` running?"
            ) from e
        except httpx.TimeoutException as e:
            raise LLMUnavailableError(
                "Ollama request timed out. Try a smaller model or raise LLM_TIMEOUT_S."
            ) from e
        if resp.status_code == 404 and model:
            raise ModelNotFoundError(f"Model '{model}' is not installed. Run: ollama pull {model}")
        if resp.status_code >= 400:
            raise LLMError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()
