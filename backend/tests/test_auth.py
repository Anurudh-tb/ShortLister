import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from services.users import UserStore, hash_password, verify_password
from tests.conftest import ScriptedProvider


def signup(client, username: str, password: str):
    return client.post("/api/auth/signup", json={"username": username, "password": password})


def login(client, username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_argon2_hash_roundtrip_and_salted():
    h = hash_password("s3cret-pw")
    assert h.startswith("$argon2id$")
    assert verify_password("s3cret-pw", h)
    assert not verify_password("wrong", h)
    assert h != hash_password("s3cret-pw")
    assert not verify_password("s3cret-pw", "$argon2id$garbage")


def test_signup_then_login(client_with):
    client = client_with(ScriptedProvider([]))

    r = signup(client, " New.User@Example.com ", "Passw0rd!")
    assert r.status_code == 201
    created = r.json()
    assert created["username"] == "new.user@example.com" and created["id"] > 0 and created["created_at"]
    assert "password" not in created

    with client.app.state.db.session() as s:
        stored = UserStore(client.app.state.db)._find(s, "new.user@example.com").password
    assert stored.startswith("$argon2id$") and "Passw0rd!" not in stored

    r = signup(client, "NEW.USER@example.com", "Passw0rd!")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "username_taken"

    ok = login(client, "New.User@example.com", "Passw0rd!")
    assert ok.status_code == 200
    body = ok.json()
    assert body["username"] == "new.user@example.com"
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    assert client.app.state.tokens.verify(body["access_token"]).username == "new.user@example.com"

    for username, password in (("new.user@example.com", "nope"), ("nobody@example.com", "Passw0rd!")):
        r = login(client, username, password)
        assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_credentials"
    assert UserStore(client.app.state.db).delete("new.user@example.com")


def test_signup_validation(client_with):
    client = client_with(ScriptedProvider([]))
    for username, password in (("x", "Passw0rd!"), ("has space", "Passw0rd!"), ("ok.user", "short1"),
                               ("ok.user", "lettersonly"), ("ok.user", "12345678")):
        r = signup(client, username, password)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_signup", (username, password)
    assert signup(client, "", "").status_code == 422
    assert UserStore(client.app.state.db).list_usernames().count("ok.user") == 0


def test_database_rejects_plaintext_passwords_and_unnormalized_usernames(client_with):
    client = client_with(ScriptedProvider([]))
    db = client.app.state.db
    for username, password in (("plain.user", "plain-pw-1"), ("pbkdf2.user", "pbkdf2_sha256$1$00$00"),
                               ("Mixed.Case", hash_password("Passw0rd1")), (" padded ", hash_password("Passw0rd1"))):
        with pytest.raises(IntegrityError), db.session() as s:
            # Raw SQL, like a hand-written INSERT in Workbench (bypasses the app's own normalization).
            s.execute(text("INSERT INTO users (username, password) VALUES (:u, :p)"), {"u": username, "p": password})
    with pytest.raises(IntegrityError), db.session() as s:
        s.execute(text("INSERT INTO users (username, password) VALUES ('dup.user', :p), ('dup.user', :p)"),
                  {"p": hash_password("Passw0rd1")})
    assert UserStore(db).list_usernames() == []


def test_unknown_username_still_runs_a_full_password_check(client_with, monkeypatch):
    import services.users as users_mod

    client = client_with(ScriptedProvider([]))
    assert signup(client, "timing.user", "Passw0rd!").status_code == 201
    checked: list[str] = []
    real = users_mod._hasher

    class Spy:  # PasswordHasher's methods are read-only, so wrap it
        def verify(self, h: str, pw: str) -> bool:
            checked.append(h)
            return real.verify(h, pw)

        def check_needs_rehash(self, h: str) -> bool:
            return real.check_needs_rehash(h)

    monkeypatch.setattr(users_mod, "_hasher", Spy())

    assert login(client, "no.such.user", "Passw0rd!").status_code == 401
    assert login(client, "timing.user", "wrong-pw-1").status_code == 401
    assert checked[0] == users_mod._DUMMY_HASH and checked[1] != users_mod._DUMMY_HASH
    assert UserStore(client.app.state.db).delete("timing.user")


def test_migration_hashes_plaintext_normalizes_and_adds_nothing_twice(tmp_path):
    from models.db import Database
    from services.user_migration import MigrationBlocked, migrate_users

    def legacy_db(rows):
        path = tmp_path / f"legacy{len(list(tmp_path.iterdir()))}.db"
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(150) UNIQUE, "
                    "password VARCHAR(255), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        con.executemany("INSERT INTO users (username, password) VALUES (?, ?)", rows)
        con.commit()
        con.close()
        return Database(f"sqlite:///{path}")

    db = legacy_db([(" Old.User ", "plain-pw-1"), ("ok.user", hash_password("Passw0rd1"))])
    report = migrate_users(db)
    assert report.hashed == ["old.user"] and report.renamed == [(" Old.User ", "old.user")]
    users = UserStore(db)
    assert users.list_usernames() == ["ok.user", "old.user"]
    assert users.authenticate("old.user", "plain-pw-1") == "old.user"
    again = migrate_users(db)
    assert again.hashed == [] and again.renamed == []
    db.dispose()

    blocked = legacy_db([("Same", "x"), ("same", "y")])
    with pytest.raises(MigrationBlocked, match="same after normalization"):
        migrate_users(blocked)
    with blocked.session() as s:  # nothing changed
        assert s.execute(text("SELECT password FROM users ORDER BY id")).scalars().all() == ["x", "y"]
    blocked.dispose()

    legacy = legacy_db([("legacy.user", "pbkdf2_sha256$1000$00$00")])
    with pytest.raises(MigrationBlocked, match="PBKDF2"):
        migrate_users(legacy)
    legacy.dispose()


def test_failed_logins_lock_the_account(client_with, monkeypatch):
    from app.main import settings

    monkeypatch.setattr(settings, "login_max_failures", 3)
    client = client_with(ScriptedProvider([]))
    assert signup(client, "locked.user", "Passw0rd!").status_code == 201
    assert login(client, "locked.user", "Passw0rd!").status_code == 200  # success clears the count

    for _ in range(3):
        assert login(client, "locked.user", "wrong-pw-1").status_code == 401
    r = login(client, " LOCKED.user ", "Passw0rd!")  # right password, but locked (same account after normalization)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "too_many_requests"
    assert int(r.headers["Retry-After"]) > 0
    assert login(client, "other.user", "wrong-pw-1").status_code == 401  # other accounts unaffected

    client.app.state.rate_limiter.failures.reset("locked.user")  # window passed
    assert login(client, "locked.user", "Passw0rd!").status_code == 200
    assert UserStore(client.app.state.db).delete("locked.user")


def test_per_ip_rate_limit(client_with, monkeypatch):
    from app.main import settings

    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 3)
    client = client_with(ScriptedProvider([]))
    for i in range(3):
        assert signup(client, f"ip.user{i}", "Passw0rd!").status_code == 201
    r = signup(client, "ip.user3", "Passw0rd!")
    assert r.status_code == 429 and "Try again in" in r.json()["detail"]["detail"]
    for _ in range(3):
        assert login(client, "ip.user0", "Passw0rd!").status_code == 200  # login has its own budget
    assert login(client, "ip.user0", "Passw0rd!").status_code == 429
    users = UserStore(client.app.state.db)
    for i in range(3):
        assert users.delete(f"ip.user{i}")


def test_short_lived_token_is_renewed_while_active(client_with, monkeypatch):
    from datetime import UTC, datetime, timedelta

    import jwt

    from app.main import settings

    monkeypatch.setattr(settings, "auth_required", True)
    client = client_with(ScriptedProvider([]))
    tokens = client.app.state.tokens
    assert tokens.expires_in == 15 * 60

    fresh = tokens.issue("renew.user")
    r = client.get("/api/jobs", headers={"Authorization": f"Bearer {fresh}"})
    assert r.status_code == 200 and "X-Access-Token" not in r.headers

    half_used = jwt.encode({"sub": "renew.user", "exp": datetime.now(UTC) + timedelta(minutes=5)},
                           tokens._secret, algorithm="HS256")
    r = client.get("/api/jobs", headers={"Authorization": f"Bearer {half_used}"})
    assert r.status_code == 200
    renewed = r.headers["X-Access-Token"]
    assert int(r.headers["X-Access-Token-Expires-In"]) == 15 * 60
    claims = tokens.verify(renewed)
    assert claims.username == "renew.user" and claims.expires_at > datetime.now(UTC) + timedelta(minutes=14)


def test_api_requires_valid_token(client_with, monkeypatch):
    from datetime import UTC, datetime, timedelta

    import jwt

    from app.main import settings

    monkeypatch.setattr(settings, "auth_required", True)
    client = client_with(ScriptedProvider([]))
    assert signup(client, "tok.user", "Passw0rd!").status_code == 201  # sign-up needs no token
    token = login(client, "tok.user", "Passw0rd!").json()["access_token"]

    assert client.get("/api/health").status_code == 200
    r = client.get("/api/jobs")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "not_authenticated"
    assert client.get("/api/jobs", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    expired = jwt.encode({"sub": "tok.user", "exp": datetime.now(UTC) - timedelta(minutes=1)},
                         client.app.state.tokens._secret, algorithm="HS256")
    forged = jwt.encode({"sub": "tok.user", "exp": datetime.now(UTC) + timedelta(hours=1)}, "x" * 32, algorithm="HS256")
    for bad in (tampered, expired, forged, "not-a-jwt"):
        r = client.get("/api/jobs", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_token"
    assert UserStore(client.app.state.db).delete("tok.user")
