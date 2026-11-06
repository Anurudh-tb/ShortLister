"""OpenAI-compatible chat-completions provider, used for LLM_MODE=online.

Defaults to Groq's free tier, but works with any OpenAI-compatible endpoint (Gemini, OpenRouter,
Together, a local vLLM/LM Studio server, ...) by changing ONLINE_BASE_URL / ONLINE_MODEL_NAME.
"""
import asyncio
import json
import logging
from typing import Any, Literal

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

JsonMode = Literal["json_object", "json_schema"]

# json_object mode does not enforce the schema, so it is spelled out for the model instead.
# (Groq also requires the word "JSON" to appear in the messages for this mode.)
_SCHEMA_INSTRUCTION = "Respond with a single JSON object that conforms to this JSON Schema:\n{schema}"
_MAX_RATE_LIMIT_WAITS = 3
_MAX_RATE_LIMIT_WAIT_S = 30.0


class OpenAICompatProvider(LLMProvider):
    name = "online"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float,
        json_mode: JsonMode = "json_object",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._json_mode = json_mode
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
        )

    async def chat_json(
        self,
        messages: list[ChatMessage],
        json_schema: dict[str, Any],
        *,
        model: str,
        temperature: float = 0.0,
        num_ctx: int | None = None,  # context size is fixed by the hosted model
    ) -> str:
        msgs = [{"role": m.role, "content": m.content} for m in messages]
        if self._json_mode == "json_schema":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": json_schema.get("title", "response"), "schema": json_schema},
            }
        else:
            response_format = {"type": "json_object"}
            msgs.insert(0, {"role": "system", "content": _SCHEMA_INSTRUCTION.format(schema=json.dumps(json_schema))})
        payload = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "seed": 42,
            "response_format": response_format,
        }
        data = await self._request("POST", "/chat/completions", json=payload, model=model)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str):
            raise LLMError("Online LLM response did not contain message content")
        logger.debug("online chat ok model=%s usage=%s", model, data.get("usage"))
        return content

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request("GET", "/models")
        out = [
            ModelInfo(name=m["id"], family=m.get("owned_by"))
            for m in data.get("data", [])
            if isinstance(m, dict) and m.get("id")
        ]
        return sorted(out, key=lambda m: m.name)

    async def _request(self, method: str, path: str, *, json: Any = None, model: str | None = None) -> dict[str, Any]:
        for attempt in range(_MAX_RATE_LIMIT_WAITS + 1):
            try:
                resp = await self._client.request(method, path, json=json)
            except httpx.ConnectError as e:
                raise LLMUnavailableError(f"Cannot reach the online LLM at {self._base_url}. Check your network.") from e
            except httpx.TimeoutException as e:
                raise LLMUnavailableError("Online LLM request timed out. Raise LLM_TIMEOUT_S or retry.") from e
            if resp.status_code != 429 or attempt == _MAX_RATE_LIMIT_WAITS:
                break
            wait = _retry_after_s(resp, default=2.0 * (attempt + 1))
            logger.warning("online LLM rate-limited; retrying in %.1fs (attempt %d)", wait, attempt + 1)
            await asyncio.sleep(wait)

        if resp.status_code in (401, 403):
            raise LLMUnavailableError("Online LLM rejected the API key. Check ONLINE_API_KEY.")
        if resp.status_code == 429:
            raise LLMUnavailableError("Online LLM free-tier rate limit reached. Wait a minute and retry.")
        if resp.status_code == 404 and model:
            raise ModelNotFoundError(f"Model '{model}' is not available at {self._base_url}. Check ONLINE_MODEL_NAME.")
        if resp.status_code >= 400:
            raise LLMError(f"Online LLM returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def aclose(self) -> None:
        await self._client.aclose()


def _retry_after_s(resp: httpx.Response, default: float) -> float:
    try:
        return min(float(resp.headers["retry-after"]), _MAX_RATE_LIMIT_WAIT_S)
    except (KeyError, ValueError):
        return default
