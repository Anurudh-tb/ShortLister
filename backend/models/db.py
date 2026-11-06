"""SQLAlchemy models and session factory (MySQL or SQLite, chosen by DATABASE_URL)."""
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker, validates


# MySQL's TEXT caps at 64 KB; result JSON and resume text can exceed that.
LongText = Text().with_variant(LONGTEXT(), "mysql")


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    status: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))
    rubric_json: Mapped[str | None] = mapped_column(LongText)
    error: Mapped[str | None] = mapped_column(Text)

    candidates: Mapped[list["CandidateRow"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="CandidateRow.position"
    )


class CandidateRow(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(16), default="pending")
    total_score: Mapped[float | None] = mapped_column(Float)
    must_have_ok: Mapped[bool | None] = mapped_column(Boolean)
    # Full CandidateResult as JSON (scores, evidence, reasoning, strengths, gaps...).
    result_json: Mapped[str] = mapped_column(LongText)
    # Only populated when PERSIST_RESUME_TEXT=true.
    resume_text: Mapped[str | None] = mapped_column(LongText)

    job: Mapped[JobRow] = relationship(back_populates="candidates")


class RubricCacheRow(Base):
    """Rubric generated for a JD + model, so re-running the same JD gives the same rubric without the LLM."""

    __tablename__ = "rubric_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    model: Mapped[str] = mapped_column(String(200))
    rubric_json: Mapped[str] = mapped_column(LongText)


class ScoreCacheRow(Base):
    """A resume's score for a rubric + model. Keyed by content hashes; the resume text itself is not stored."""

    __tablename__ = "score_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    resume_hash: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(200))
    candidate_name: Mapped[str | None] = mapped_column(String(200))
    best_fit_role: Mapped[str | None] = mapped_column(String(200))
    total_score: Mapped[float | None] = mapped_column(Float)
    # CandidateResult as JSON, without job-specific fields (id, filename, decision, notes).
    result_json: Mapped[str] = mapped_column(LongText)


# Database-level guarantees for `users` (see manage_users.py migrate for existing tables). MySQL compares
# text case-insensitively under utf8mb4_unicode_ci, so its normalization check compares bytes (utf8mb4_bin).
_USERNAME_NORMALIZED = "ck_users_username_normalized"
_PASSWORD_HASHED = "ck_users_password_hashed"
USER_CHECKS_MYSQL = {
    _USERNAME_NORMALIZED: "username COLLATE utf8mb4_bin = LOWER(TRIM(username)) COLLATE utf8mb4_bin",
    _PASSWORD_HASHED: "password LIKE '$argon2%'",
}


class UserRow(Base):
    """A person who can sign in. `username` is stored trimmed and lowercase; `password` is an Argon2 hash."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(USER_CHECKS_MYSQL[_USERNAME_NORMALIZED], name=_USERNAME_NORMALIZED).ddl_if(dialect="mysql"),
        CheckConstraint("username = lower(trim(username))", name=_USERNAME_NORMALIZED).ddl_if(dialect="sqlite"),
        CheckConstraint(USER_CHECKS_MYSQL[_PASSWORD_HASHED], name=_PASSWORD_HASHED),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    # Server default too, so a hand-written INSERT can leave it out.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )

    @validates("username")
    def _normalize_username(self, _key: str, value: str) -> str:
        return value.strip().lower()


class Database:
    def __init__(self, url: str) -> None:
        if url.startswith("sqlite"):
            self.engine: Engine = create_engine(url, connect_args={"check_same_thread": False})
            event.listen(self.engine, "connect", _sqlite_pragmas)
        else:
            # MySQL drops idle connections (wait_timeout); check and recycle them.
            self.engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._sessions() as s, s.begin():
            yield s

    def dispose(self) -> None:
        self.engine.dispose()


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()
