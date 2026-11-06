"""User accounts: sign-up validation, password hashing and sign-in checks.

Passwords are hashed with Argon2id (argon2-cffi); the database only accepts Argon2 hashes
(ck_users_password_hashed). Usernames are stored trimmed and lowercase (ck_users_username_normalized).
"""
import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.db import Database, UserRow

_hasher = PasswordHasher()

_USERNAME_RE = re.compile(r"^[a-z0-9._@+-]{3,150}$")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def is_hashed(stored: str) -> bool:
    return stored.startswith("$argon2")


def _verify(password: str, stored: str) -> tuple[bool, bool]:
    """Return (matches, needs_rehash). Anything that isn't an Argon2 hash never matches."""
    try:
        _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False, False
    return True, _hasher.check_needs_rehash(stored)


def verify_password(password: str, stored: str) -> bool:
    return _verify(password, stored)[0]


def normalize_username(username: str) -> str:
    return username.strip().lower()


# Verified against when the username doesn't exist, so an unknown username costs the same Argon2 work
# (and response time) as a wrong password and can't be told apart by timing.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class UserExistsError(Exception):
    pass


class InvalidUserInputError(ValueError):
    """Username or password doesn't meet the rules; the message says why."""


def validate_new_credentials(username: str, password: str, *, min_length: int) -> str:
    """Return the normalized username, or raise InvalidUserInputError with a readable reason."""
    name = normalize_username(username)
    if not _USERNAME_RE.fullmatch(name):
        raise InvalidUserInputError(
            "Username must be 3-150 characters: letters, numbers and . _ @ + - only (an email address works)."
        )
    if len(password) < min_length or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise InvalidUserInputError(f"Password must be at least {min_length} characters with a letter and a number.")
    return name


class UserStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _find(self, s, username: str) -> UserRow | None:  # type: ignore[no-untyped-def]
        # Stored names are always normalized, so an exact match uses the unique index.
        return s.scalar(select(UserRow).where(UserRow.username == normalize_username(username)))

    def create(self, username: str, password: str) -> UserRow:
        """Insert a user (no rule checks; callers validate). Raises UserExistsError if the name is taken."""
        name = normalize_username(username)
        if not name or not password:
            raise ValueError("username and password are required")
        try:
            with self._db.session() as s:
                if self._find(s, name) is not None:
                    raise UserExistsError(name)
                row = UserRow(username=name, password=hash_password(password))
                s.add(row)
                s.flush()
        except IntegrityError as e:
            raise UserExistsError(name) from e
        return row

    def signup(self, username: str, password: str, *, min_length: int) -> UserRow:
        return self.create(validate_new_credentials(username, password, min_length=min_length), password)

    def set_password(self, username: str, password: str) -> bool:
        with self._db.session() as s:
            row = self._find(s, username)
            if row is None:
                return False
            row.password = hash_password(password)
            return True

    def delete(self, username: str) -> bool:
        with self._db.session() as s:
            row = self._find(s, username)
            if row is None:
                return False
            s.delete(row)
            return True

    def list_usernames(self) -> list[str]:
        with self._db.session() as s:
            return list(s.scalars(select(UserRow.username).order_by(UserRow.username)))

    def authenticate(self, username: str, password: str) -> str | None:
        """Return the username if the credentials are valid, else None. Rehashes if Argon2 settings changed."""
        with self._db.session() as s:
            row = self._find(s, username)
            ok, needs_rehash = _verify(password, row.password if row else _DUMMY_HASH)
            if not (row and ok):
                return None
            if needs_rehash:
                row.password = hash_password(password)
            return row.username
