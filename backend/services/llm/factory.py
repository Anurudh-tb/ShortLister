"""Builds the configured LLMProvider. Add new providers here."""
from app.config import Settings
from services.llm.base import LLMProvider
from services.llm.mock import MockProvider
from services.llm.ollama import OllamaProvider
from services.llm.openai_compat import OpenAICompatProvider


def build_provider(settings: Settings) -> LLMProvider:
    provider = settings.effective_provider
    if provider == "ollama":
        return OllamaProvider(settings.ollama_host, settings.llm_timeout_s, settings.num_ctx)
    if provider == "online":
        if settings.online_api_key is None or not settings.online_api_key.get_secret_value():
            raise ValueError("LLM_MODE=online requires ONLINE_API_KEY (get a free Groq key at https://console.groq.com/keys)")
        return OpenAICompatProvider(
            settings.online_base_url,
            settings.online_api_key.get_secret_value(),
            settings.llm_timeout_s,
            settings.online_json_mode,
        )
    if provider == "mock":
        return MockProvider()
    raise ValueError(f"Unknown LLM provider: {provider}")
