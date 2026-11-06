"""FastAPI dependencies."""
from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

from services.jobs import JobManager
from services.llm.base import LLMProvider
from services.auth_tokens import InvalidTokenError, TokenService
from services.rate_limit import AuthRateLimiter
from services.users import UserStore


def get_provider(request: Request) -> LLMProvider:
    return request.app.state.provider


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.jobs


def get_user_store(request: Request) -> UserStore:
    return UserStore(request.app.state.db)


def get_rate_limiter(request: Request) -> AuthRateLimiter:
    return request.app.state.rate_limiter


def get_token_service(request: Request) -> TokenService:
    return request.app.state.tokens


_bearer = HTTPBearer(auto_error=False)


# Response headers carrying a renewed access token (see Settings.jwt_expire_minutes).
RENEWED_TOKEN_HEADER = "X-Access-Token"
RENEWED_TOKEN_EXPIRES_HEADER = "X-Access-Token-Expires-In"


def require_user(
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    tokens: TokenService = Depends(get_token_service),
    settings: Settings = Depends(get_settings),
) -> str | None:
    """Username from the `Authorization: Bearer <token>` header; 401 if it's missing or invalid.

    Past half its lifetime, a fresh token is returned in the X-Access-Token response header.
    """
    if not settings.auth_required:
        return None
    if credentials is None:
        raise HTTPException(401, {"code": "not_authenticated", "detail": "Sign in to continue."},
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = tokens.verify(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(401, {"code": "invalid_token", "detail": "Your sign-in has expired. Sign in again."},
                            headers={"WWW-Authenticate": "Bearer"}) from None
    if tokens.should_renew(claims):
        response.headers[RENEWED_TOKEN_HEADER] = tokens.issue(claims.username)
        response.headers[RENEWED_TOKEN_EXPIRES_HEADER] = str(tokens.expires_in)
    return claims.username
