from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.deps import get_rate_limiter, get_token_service, get_user_store
from services.auth_tokens import TokenService
from services.rate_limit import AuthRateLimiter
from services.users import InvalidUserInputError, UserExistsError, UserStore, normalize_username

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=1024)


class SignupResponse(BaseModel):
    id: int
    username: str
    created_at: datetime


class LoginResponse(BaseModel):
    username: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/signup", response_model=SignupResponse, status_code=201)
def signup(
    body: Credentials,
    request: Request,
    users: UserStore = Depends(get_user_store),
    settings: Settings = Depends(get_settings),
    limiter: AuthRateLimiter = Depends(get_rate_limiter),
) -> SignupResponse:
    """Register a new user. The password is stored only as an Argon2 hash."""
    limiter.ip.hit(f"signup:{_client_ip(request)}")
    try:
        row = users.signup(body.username, body.password, min_length=settings.password_min_length)
    except InvalidUserInputError as e:
        raise HTTPException(422, {"code": "invalid_signup", "detail": str(e)}) from None
    except UserExistsError:
        raise HTTPException(409, {"code": "username_taken", "detail": "That username is already taken."}) from None
    return SignupResponse(id=row.id, username=row.username, created_at=row.created_at)


@router.post("/login", response_model=LoginResponse)
def login(
    body: Credentials,
    request: Request,
    users: UserStore = Depends(get_user_store),
    tokens: TokenService = Depends(get_token_service),
    limiter: AuthRateLimiter = Depends(get_rate_limiter),
) -> LoginResponse:
    """Check the credentials and return a JWT for the Authorization: Bearer header."""
    limiter.ip.hit(f"login:{_client_ip(request)}")
    account = normalize_username(body.username)
    # Checked before the password, so a blocked account can't be probed further.
    limiter.failures.check(account)
    username = users.authenticate(body.username, body.password)
    if username is None:
        limiter.failures.hit(account)
        raise HTTPException(401, {"code": "invalid_credentials", "detail": "Incorrect username or password."})
    limiter.failures.reset(account)
    return LoginResponse(username=username, access_token=tokens.issue(username), expires_in=tokens.expires_in)
