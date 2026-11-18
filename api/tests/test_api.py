"""Integration tests: auth flow + conversations + settings (TestClient)."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine
from sqlmodel.pool import StaticPool

from app.db import models  # noqa: F401
from app.db.session import get_session
from app.main import create_app


@pytest.fixture(name="client")
def client_fixture(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    from sqlmodel import SQLModel

    SQLModel.metadata.create_all(engine)

    app = create_app()

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def test_register_login_me(client):
    r = client.post(
        "/auth/register",
        json={"email": "rafi@example.com", "password": "supersecret1", "name": "Rafi"},
    )
    assert r.status_code == 201, r.text
    tokens = r.json()
    assert tokens["access_token"]
    assert tokens["user"]["email"] == "rafi@example.com"

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["name"] == "Rafi"

    login = client.post(
        "/auth/login", json={"email": "rafi@example.com", "password": "supersecret1"}
    )
    assert login.status_code == 200


def test_register_rejects_short_password(client):
    r = client.post(
        "/auth/register", json={"email": "x@example.com", "password": "short"}
    )
    assert r.status_code == 422


def test_duplicate_email_rejected(client):
    body = {"email": "dupe@example.com", "password": "supersecret1"}
    assert client.post("/auth/register", json=body).status_code == 201
    assert client.post("/auth/register", json=body).status_code == 409


def test_wrong_password_401(client):
    client.post(
        "/auth/register", json={"email": "y@example.com", "password": "supersecret1"}
    )
    r = client.post(
        "/auth/login", json={"email": "y@example.com", "password": "wrongpass123"}
    )
    assert r.status_code == 401


def test_refresh_flow(client):
    tokens = client.post(
        "/auth/register", json={"email": "z@example.com", "password": "supersecret1"}
    ).json()
    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_first_user_with_admin_email_gets_admin(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "admin_email", "boss@example.com")
    r = client.post(
        "/auth/register", json={"email": "boss@example.com", "password": "supersecret1"}
    )
    assert r.json()["user"]["role"] == "admin"


def test_conversations_crud(client):
    tokens = client.post(
        "/auth/register", json={"email": "c@example.com", "password": "supersecret1"}
    ).json()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    created = client.post(
        "/conversations", json={"title": "Test"}, headers=auth
    )
    assert created.status_code == 201
    conv_id = created.json()["id"]

    listed = client.get("/conversations", headers=auth)
    assert listed.status_code == 200
    assert any(c["id"] == conv_id for c in listed.json()["conversations"])

    patched = client.patch(
        f"/conversations/{conv_id}", json={"title": "Renamed"}, headers=auth
    )
    assert patched.json()["title"] == "Renamed"

    assert client.delete(f"/conversations/{conv_id}", headers=auth).status_code == 204


def test_conversations_need_auth(client):
    assert client.get("/conversations").status_code == 401


def test_settings_roundtrip(client):
    tokens = client.post(
        "/auth/register", json={"email": "s@example.com", "password": "supersecret1"}
    ).json()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    r = client.put(
        "/auth/settings",
        json={"theme": "dark", "default_lang": "bn", "auto_play": False},
        headers=auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["theme"] == "dark"
    assert body["default_lang"] == "bn"
    assert body["auto_play"] is False


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "engines" in body


def test_languages(client):
    r = client.get("/languages")
    codes = [lang["code"] for lang in r.json()["languages"]]
    assert "bn" in codes and "en" in codes
    assert len(codes) == 20
