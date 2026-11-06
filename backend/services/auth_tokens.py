"""Signed sign-in tokens (JWT, HS256) via PyJWT."""
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.config import Settings

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


@dataclass
class TokenClaims:
    username: str
    expires_at: datetime


class TokenService:
    def __init__(self, settings: Settings) -> None:
        if settings.jwt_secret and settings.jwt_secret.get_secret_value():
            self._secret = settings.jwt_secret.get_secret_value()
        else:
            logger.warning("JWT_SECRET is not set; using a random secret, so sign-ins end when the backend restarts")
            self._secret = secrets.token_urlsafe(48)
        self._ttl = timedelta(minutes=settings.jwt_expire_minutes)

    @property
    def expires_in(self) -> int:
        """Token lifetime in seconds."""
        return int(self._ttl.total_seconds())

    def issue(self, username: str) -> str:
        now = datetime.now(UTC)
        return jwt.encode({"sub": username, "iat": now, "exp": now + self._ttl}, self._secret, algorithm=_ALGORITHM)

    def should_renew(self, claims: TokenClaims) -> bool:
        """True once less than half of the token's lifetime is left."""
        return claims.expires_at - datetime.now(UTC) < self._ttl / 2

    def verify(self, token: str) -> TokenClaims:
        """Return the claims of a valid token; raise InvalidTokenError otherwise (bad signature, expired...)."""
        try:
            claims = jwt.decode(token, self._secret, algorithms=[_ALGORITHM], options={"require": ["sub", "exp"]})
        except jwt.PyJWTError as e:
            raise InvalidTokenError(str(e)) from e
        return TokenClaims(username=claims["sub"], expires_at=datetime.fromtimestamp(claims["exp"], UTC))
