import json

import httpx
import pytest

from app.config import Settings
from services.llm.base import ChatMessage, LLMUnavailableError, ModelNotFoundError
from services.llm.factory import build_provider
from services.llm.mock import MockProvider
from services.llm.ollama import OllamaProvider
from services.llm import openai_compat
from services.llm.openai_compat import OpenAICompatProvider

SCHEMA = {"title": "Thing", "type": "object", "properties": {"x": {"type": "integer"}}}
MESSAGES = [ChatMessage("system", "sys"), ChatMessage("user", "hi")]


def make(handler, json_mode="json_object") -> OpenAICompatProvider:
    return OpenAICompatProvider("https://example.test/v1", "sk-test", 10, json_mode, transport=httpx.MockTransport(handler))


def completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


async def test_chat_json_object_mode_sends_schema_instruction() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return completion('{"x": 1}')

    out = await make(handler).chat_json(MESSAGES, SCHEMA, model="m")
    assert out == '{"x": 1}'
    req = seen[0]
    body = json.loads(req.content)
    assert req.url.path == "/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-test"
    assert body["model"] == "m" and body["response_format"] == {"type": "json_object"}
    assert "JSON" in body["messages"][0]["content"] and '"Thing"' in body["messages"][0]["content"]
    assert [m["content"] for m in body["messages"][1:]] == ["sys", "hi"]


async def test_chat_json_schema_mode() -> None:
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return completion("{}")

    await make(handler, "json_schema").chat_json(MESSAGES, SCHEMA, model="m")
    rf = seen[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["name"] == "Thing"
    assert len(seen[0]["messages"]) == 2


async def test_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(openai_compat.asyncio, "sleep", no_sleep)
    responses = [httpx.Response(429, headers={"retry-after": "1"}), completion("{}")]
    assert await make(lambda _: responses.pop(0)).chat_json(MESSAGES, SCHEMA, model="m") == "{}"


@pytest.mark.parametrize(("status", "error"), [(401, LLMUnavailableError), (404, ModelNotFoundError)])
async def test_http_errors_map_to_llm_errors(status: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        await make(lambda _: httpx.Response(status, json={})).chat_json(MESSAGES, SCHEMA, model="m")


async def test_list_models() -> None:
    data = {"data": [{"id": "b-model", "owned_by": "x"}, {"id": "a-model"}]}
    models = await make(lambda _: httpx.Response(200, json=data)).list_models()
    assert [m.name for m in models] == ["a-model", "b-model"]


def test_mode_flag_selects_provider() -> None:
    offline = Settings(_env_file=None, llm_mode="offline", llm_provider=None)
    online = Settings(_env_file=None, llm_mode="online", llm_provider=None, online_api_key="k", online_model_name="groq-m")
    assert isinstance(build_provider(offline), OllamaProvider) and offline.active_model == offline.model_name
    assert isinstance(build_provider(online), OpenAICompatProvider) and online.active_model == "groq-m"
    assert isinstance(build_provider(Settings(_env_file=None, llm_mode="online", llm_provider="mock")), MockProvider)


def test_online_mode_requires_api_key() -> None:
    with pytest.raises(ValueError, match="ONLINE_API_KEY"):
        build_provider(Settings(_env_file=None, llm_mode="online", llm_provider=None, online_api_key=""))
