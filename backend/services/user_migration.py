"""One-off migration of the `users` table to the current rules (idempotent; safe to run again).

1. Passwords that aren't Argon2 hashes: plain text (typed in by hand) is hashed with Argon2. Old
   "pbkdf2_sha256$..." hashes can't be converted without the password, so they are reported and the
   migration stops; reset those with `manage_users.py passwd <username>` first.
2. Usernames are trimmed and lowercased. If that would make two rows equal, the migration stops.
3. MySQL: adds the UNIQUE(username) and CHECK constraints from models.db if they're missing.
   SQLite can't add constraints to an existing table; new SQLite tables get them from the model.

Steps 1-2 run in one transaction, so a stop leaves the table unchanged.
"""
from dataclasses import dataclass, field

from sqlalchemy import select, text

from models.db import USER_CHECKS_MYSQL, Database, UserRow
from services.users import hash_password, is_hashed, normalize_username


class MigrationBlocked(Exception):
    pass


@dataclass
class MigrationReport:
    hashed: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    constraints_added: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def migrate_users(db: Database) -> MigrationReport:
    report = MigrationReport()
    with db.session() as s:
        rows = list(s.scalars(select(UserRow).order_by(UserRow.id)))
        legacy = [r.username for r in rows if r.password.startswith("pbkdf2_sha256$")]
        if legacy:
            raise MigrationBlocked(f"old PBKDF2 hashes can't be converted; reset these passwords first: {legacy}")
        seen: dict[str, str] = {}
        for r in rows:
            # Read the raw column value: the ORM validator only normalizes on assignment.
            raw = s.execute(select(UserRow.__table__.c.username).where(UserRow.id == r.id)).scalar_one()
            name = normalize_username(raw)
            if name in seen:
                raise MigrationBlocked(f"usernames {seen[name]!r} and {raw!r} are the same after normalization")
            seen[name] = raw
        for r in rows:
            raw = seen[normalize_username(r.username)]
            if raw != normalize_username(raw):
                r.username = raw  # validator stores the normalized form
                report.renamed.append((raw, r.username))
            if not is_hashed(r.password):
                r.password = hash_password(r.password)
                report.hashed.append(r.username)

    if db.engine.dialect.name == "mysql":
        report.constraints_added = _add_mysql_constraints(db)
    elif db.engine.dialect.name == "sqlite":
        report.notes.append("SQLite: existing tables keep their constraints; new tables get them from the model.")
    return report


def _add_mysql_constraints(db: Database) -> list[str]:
    added = []
    with db.engine.begin() as conn:
        existing = {
            (name, ctype)
            for name, ctype in conn.execute(text(
                "SELECT CONSTRAINT_NAME, CONSTRAINT_TYPE FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users'"))
        }
        unique_on_username = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'users' AND COLUMN_NAME = 'username' AND NON_UNIQUE = 0 AND SEQ_IN_INDEX = 1")).scalar()
        if not unique_on_username:
            conn.execute(text("ALTER TABLE users ADD CONSTRAINT uq_users_username UNIQUE (username)"))
            added.append("uq_users_username")
        for name, expr in USER_CHECKS_MYSQL.items():
            if (name, "CHECK") not in existing:
                conn.execute(text(f"ALTER TABLE users ADD CONSTRAINT {name} CHECK ({expr})"))
                added.append(name)
    return added
