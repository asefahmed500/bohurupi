"""Security regression tests: JWT type confusion, expiry, signatures, role
claim trust, account state, bcrypt 72-byte policy, per-IP rate limits."""

import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.config import settings
from app.db import models  # noqa: F401
from app.db.models import User
from app.db.session import get_session
from app.main import create_app
from app.security import (
    PASSWORD_MAX_BYTES,
    assert_security_config,
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)


@pytest.fixture(name="env")
def env_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    app = create_app()

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app), engine


def _register(client: TestClient, email: str, password: str = "supersecret1") -> dict:
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _set_active(engine, user_id: str, active: bool) -> None:
    with Session(engine) as s:
        u = s.get(User, user_id)
        assert u is not None
        u.is_active = active
        s.add(u)
        s.commit()


# ---- token type confusion ------------------------------------------------


def test_refresh_token_cannot_be_used_as_access(env):
    c, _engine = env
    tokens = _register(c, "confuse@example.com")
    r = c.get("/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401
    r = c.get("/conversations", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401


def test_access_token_cannot_be_used_as_refresh(env):
    c, _engine = env
    tokens = _register(c, "accessrefresh@example.com")
    r = c.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401


# ---- expiry / signature / algorithm ---------------------------------------


def test_expired_access_token_rejected(env, monkeypatch):
    c, _engine = env
    monkeypatch.setattr(settings, "access_token_expire_minutes", -1)
    tok = create_access_token("whatever-user")
    r = c.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_expired_refresh_token_rejected(env, monkeypatch):
    c, _engine = env
    tokens = _register(c, "exprefresh@example.com")
    monkeypatch.setattr(settings, "refresh_token_expire_days", -1)
    expired = create_refresh_token(tokens["user"]["id"])
    r = c.post("/auth/refresh", json={"refresh_token": expired})
    assert r.status_code == 401


def test_forged_signature_rejected(env):
    c, _engine = env
    tokens = _register(c, "forge@example.com")
    payload = {
        "sub": tokens["user"]["id"],
        "type": "access",
        "role": "admin",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    forged = pyjwt.encode(payload, "attacker-signing-secret-0123456789", algorithm="HS256")
    r = c.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401
    # a flipped byte on a real token must also fail
    tampered = tokens["access_token"][:-3] + "aaa"
    r = c.get("/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401


def test_alg_none_token_rejected(env):
    c, _engine = env
    tokens = _register(c, "nonealg@example.com")
    payload = {
        "sub": tokens["user"]["id"],
        "type": "access",
        "role": "admin",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    unsigned = pyjwt.encode(payload, key="", algorithm="none")
    r = c.get("/auth/me", headers={"Authorization": f"Bearer {unsigned}"})
    assert r.status_code == 401


# ---- role claim must never be trusted -------------------------------------


def test_admin_role_claim_is_not_trusted(env):
    """A token signed with the real secret but carrying role=admin must NOT
    grant admin endpoints: require_admin reads the role from the DB."""
    c, _engine = env
    tokens = _register(c, "notadmin@example.com")
    now = int(time.time())
    payload = {
        "sub": tokens["user"]["id"],
        "type": "access",
        "role": "admin",
        "iat": now,
        "exp": now + 300,
    }
    lying_token = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    r = c.get("/admin/users", headers={"Authorization": f"Bearer {lying_token}"})
    assert r.status_code == 403
    r = c.post(
        "/admin/engines/edge",
        headers={"Authorization": f"Bearer {lying_token}"},
        json={"enabled": False},
    )
    assert r.status_code == 403


# ---- account state ---------------------------------------------------------


def test_inactive_user_me_401_and_login_403(env):
    c, engine = env
    tokens = _register(c, "inactive@example.com")
    _set_active(engine, tokens["user"]["id"], False)

    r = c.get("/auth/me", headers=_auth(tokens))
    assert r.status_code == 401

    r = c.post("/auth/login", json={"email": "inactive@example.com", "password": "supersecret1"})
    assert r.status_code == 403


def test_disabled_user_refresh_rejected(env):
    c, engine = env
    tokens = _register(c, "disabled@example.com")
    _set_active(engine, tokens["user"]["id"], False)
    r = c.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


# ---- bcrypt 72-byte password policy ----------------------------------------


def test_register_rejects_password_over_72_bytes(env):
    c, _engine = env
    # pure ASCII: 73 bytes
    r = c.post("/auth/register", json={"email": "long72a@example.com", "password": "a" * 73})
    assert r.status_code == 422
    # multibyte: 25 Bengali chars = 75 bytes, but only 25 chars (passes the
    # old 128-char cap -- this is exactly the hole the byte cap closes)
    r = c.post(
        "/auth/register",
        json={"email": "long72b@example.com", "password": "আ" * 25},
    )
    assert r.status_code == 422
    # exactly at the limit is fine
    r = c.post("/auth/register", json={"email": "long72c@example.com", "password": "a" * 72})
    assert r.status_code == 201


def test_hash_password_enforces_byte_limit():
    with pytest.raises(ValueError):
        hash_password("a" * (PASSWORD_MAX_BYTES + 1))
    h = hash_password("a" * PASSWORD_MAX_BYTES)
    assert verify_password("a" * PASSWORD_MAX_BYTES, h)
    assert not verify_password("b" * PASSWORD_MAX_BYTES, h)


def test_verify_password_truncates_oversized_input():
    """Oversized login attempts are judged on the first 72 bytes (bcrypt
    semantics) instead of crashing (bcrypt >= 5 raises ValueError)."""
    h = hash_password("a" * 72)
    assert verify_password("a" * 72, h) is True
    # 200 bytes -> truncated to the first 72, which match
    assert verify_password("a" * 200, h) is True
    # a different byte anywhere in the first 72 -> no match
    assert verify_password("a" * 71 + "b", h) is False
    assert verify_password("b" * 72, h) is False
    # and a pathologically long input must not raise; it still truncates to
    # the first 72 bytes, so it matches
    assert verify_password("a" * 10_000_000, h) is True


# ---- startup guard ----------------------------------------------------------


def test_security_config_guard(monkeypatch):
    # dev with the default secret: allowed
    monkeypatch.setattr(settings, "env", "dev")
    monkeypatch.setattr(settings, "jwt_secret", "change-me-to-a-long-random-string")
    assert_security_config()

    # prod with the default secret: must refuse to start
    monkeypatch.setattr(settings, "env", "prod")
    with pytest.raises(RuntimeError):
        assert_security_config()

    # prod with a short secret: must refuse to start
    monkeypatch.setattr(settings, "jwt_secret", "too-short")
    with pytest.raises(RuntimeError):
        assert_security_config()

    # prod with a proper secret: fine
    monkeypatch.setattr(settings, "jwt_secret", "x" * 32)
    assert_security_config()

    # algorithm pin: anything but HS256 is a config error
    monkeypatch.setattr(settings, "jwt_algorithm", "none")
    monkeypatch.setattr(settings, "env", "dev")
    with pytest.raises(RuntimeError):
        assert_security_config()


# ---- per-IP rate limits -----------------------------------------------------


def test_login_rate_limited_per_ip(env, monkeypatch):
    """Rotating emails from one IP must not bypass login throttling."""
    c, _engine = env
    from app.api import auth as auth_mod

    monkeypatch.setattr(auth_mod, "_client_ip", lambda request: "ratetest-login")
    monkeypatch.setattr(auth_mod, "LOGIN_IP_LIMIT", 3)
    for i in range(3):
        r = c.post(
            "/auth/login",
            json={"email": f"rl-{i}@example.com", "password": "whatever1"},
        )
        assert r.status_code == 401
    # 4th attempt from the same IP, different email -> blocked
    r = c.post(
        "/auth/login", json={"email": "rl-other@example.com", "password": "whatever1"}
    )
    assert r.status_code == 429


def test_register_rate_limited_per_ip(env, monkeypatch):
    c, _engine = env
    from app.api import auth as auth_mod

    monkeypatch.setattr(auth_mod, "_client_ip", lambda request: "ratetest-register")
    monkeypatch.setattr(auth_mod, "REGISTER_IP_LIMIT", 2)
    def body(n: int) -> dict:
        return {"email": f"rp-{n}@example.com", "password": "supersecret1"}
    assert c.post("/auth/register", json=body(0)).status_code == 201
    assert c.post("/auth/register", json=body(1)).status_code == 201
    # different email, same IP -> blocked
    assert c.post("/auth/register", json=body(2)).status_code == 429


def test_refresh_rate_limited_per_ip(env, monkeypatch):
    c, _engine = env
    from app.api import auth as auth_mod

    monkeypatch.setattr(auth_mod, "_client_ip", lambda request: "ratetest-refresh")
    monkeypatch.setattr(auth_mod, "REFRESH_IP_LIMIT", 1)
    tokens = _register(c, "rl-refresh@example.com")
    r = c.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    r = c.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 429
