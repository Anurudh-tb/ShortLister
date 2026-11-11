"""Application settings loaded from environment / .env."""
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "offline" runs against a local Ollama server; "online" uses a hosted OpenAI-compatible API.
    llm_mode: Literal["offline", "online"] = "offline"
    # Optional explicit override of the mode. "mock" is a deterministic offline provider for demos/dev.
    llm_provider: Literal["ollama", "online", "mock"] | None = None
    ollama_host: str = "http://localhost:11434"
    model_name: str = "qwen2.5:14b"
    # Online mode. Defaults target Groq's free tier (https://console.groq.com/keys).
    online_base_url: str = "https://api.groq.com/openai/v1"
    online_api_key: SecretStr | None = None
    online_model_name: str = "llama-3.3-70b-versatile"
    # "json_object" works on every OpenAI-compatible API; "json_schema" enforces the schema
    # server-side but is only supported by some models.
    online_json_mode: Literal["json_object", "json_schema"] = "json_object"
    num_ctx: int = Field(default=8192, ge=1024)
    llm_timeout_s: float = Field(default=900.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    # Tokens reserved for the model's JSON answer when checking context fit.
    output_token_reserve: int = Field(default=1500, ge=256)

    # A must-have criterion counts as met only if its score is at least this (0-10).
    must_have_min_score: int = Field(default=5, ge=1, le=10)
    # Share of the total score (out of 100) given to the recruiter's priority prompt, when one is entered.
    priority_weight: int = Field(default=25, ge=1, le=90)
    max_resumes_per_job: int = Field(default=50, ge=1)

    max_file_mb: float = Field(default=10.0, gt=0)
    ocr_enabled: bool = False

    # e.g. mysql+pymysql://shortlister:shortlister@localhost:3306/shortlister?charset=utf8mb4
    database_url: str = "sqlite:///./shortlister.db"
    # Reuse stored rubrics / resume scores when the same JD or resume is run again with the same model.
    llm_cache_enabled: bool = True
    # Privacy: when False, extracted resume text is never written to the database.
    persist_resume_text: bool = False

    # Sign-in tokens (JWT, HS256). Set a long random JWT_SECRET in .env; without one a random secret is
    # generated at startup and everyone has to sign in again after a backend restart.
    jwt_secret: SecretStr | None = None
    # Short-lived access tokens. Active users don't get signed out: while less than half the lifetime is
    # left, every authenticated response carries a fresh token in the X-Access-Token header.
    jwt_expire_minutes: int = Field(default=15, ge=1)
    # Rate limits for POST /api/auth/login and /api/auth/signup (in memory, per process).
    auth_rate_limit_per_minute: int = Field(default=20, ge=1)  # requests per client IP, per endpoint
    login_max_failures: int = Field(default=5, ge=1)  # failed logins per username...
    login_lockout_minutes: int = Field(default=15, ge=1)  # ...within this window, then blocked until it passes
    # Sign-up rule: minimum password length (a letter and a number are also required).
    password_min_length: int = Field(default=8, ge=6, le=128)
    # Require a valid token on every /api route except health and login. Tests turn this off.
    auth_required: bool = True

    cors_origins: list[str] = ["http://localhost:4200", "http://127.0.0.1:4200"]
    log_level: str = "INFO"

    @property
    def effective_provider(self) -> Literal["ollama", "online", "mock"]:
        if self.llm_provider:
            return self.llm_provider
        return "online" if self.llm_mode == "online" else "ollama"

    @property
    def active_model(self) -> str:
        """Default model for the active provider."""
        return self.online_model_name if self.effective_provider == "online" else self.model_name

    @property
    def max_file_bytes(self) -> int:
        return int(self.max_file_mb * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
