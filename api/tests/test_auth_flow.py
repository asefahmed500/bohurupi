"""Tests: demo login (dev-only) and email-only password reset."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.config import settings
from app.db.models import Setting, User
from app.db.session import get_session
from app.main import create_app
from app.security import hash_password


@pytest.fixture(name="client")
def client_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    app = create_app()

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    with Session(engine) as s:
        demo = User(
            email=settings.demo_email,
            name=settings.demo_name,
            password_hash=hash_password(settings.demo_password),
            role="user",
            plan="free",
        )
        s.add(demo)
        s.commit()
        s.add(Setting(user_id=demo.id))
        s.commit()
    return TestClient(app), engine


def test_demo_login_dev_only(client):
    c, _ = client
    r = c.get("/auth/demo-accounts")
    assert r.status_code == 200
    assert r.json()[0]["email"] == settings.demo_email
    r = c.post("/auth/demo-login")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "user"
    assert r.json()["access_token"]

    old_env = settings.env
    settings.env = "prod"
    try:
        assert c.get("/auth/demo-accounts").status_code == 404
        assert c.post("/auth/demo-login").status_code == 404
    finally:
        settings.env = old_env


def test_password_reset_flow(client):
    c, engine = client
    # unknown email: generic response, no token leak
    r = c.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200
    assert r.json()["dev_token"] is None

    # existing email (dev, no SMTP): token surfaced for the local flow
    r = c.post("/auth/forgot-password", json={"email": settings.demo_email})
    assert r.status_code == 200
    token = r.json()["dev_token"]
    assert token and "token=" in r.json()["dev_url"]

    # reset, then log in with the new password
    r = c.post(
        "/auth/reset-password",
        json={"token": token, "new_password": "BrandNewPass123!"},
    )
    assert r.status_code == 200, r.text
    assert c.post(
        "/auth/login",
        json={"email": settings.demo_email, "password": "BrandNewPass123!"},
    ).status_code == 200
    # old password no longer works
    assert c.post(
        "/auth/login",
        json={"email": settings.demo_email, "password": settings.demo_password},
    ).status_code == 401
    # token is single-use
    assert c.post(
        "/auth/reset-password",
        json={"token": token, "new_password": "AnotherPass123!"},
    ).status_code == 400


def test_reset_rejects_invalid_and_short(client):
    c, _ = client
    bad_token = "x" * 40
    r = c.post("/auth/reset-password", json={"token": bad_token, "new_password": "short"})
    assert r.status_code in (400, 422)
    r = c.post(
        "/auth/reset-password",
        json={"token": bad_token, "new_password": "longenough123"},
    )
    assert r.status_code == 400


def test_prod_without_smtp_fails_honestly(client):
    c, _ = client
    old_env = settings.env
    settings.env = "prod"
    try:
        # cache is shared; clear any token bucket state by using a fresh address
        r = c.post("/auth/forgot-password", json={"email": settings.demo_email})
        assert r.status_code == 503, r.text
    finally:
        settings.env = old_env
