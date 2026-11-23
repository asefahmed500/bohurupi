"""Bulk history deletion, retention cleanup and signed webhook automation."""

import hashlib
import hmac
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.config import settings
from app.db.models import Conversation, WebhookDelivery
from app.db.session import get_session
from app.main import create_app
from app.services import automation, conversation_cleanup

captured: dict = {}


class Capture(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        captured["body"] = self.rfile.read(length)
        captured["headers"] = dict(self.headers)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


@pytest.fixture(name="env")
def env_fixture(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    app = create_app()

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr(automation, "engine", engine)
    monkeypatch.setattr(conversation_cleanup, "engine", engine)
    return TestClient(app), engine


def _register(c: TestClient) -> dict:
    r = c.post(
        "/auth/register",
        json={"email": f"auto-{id(c)}@example.com", "password": "supersecret1"},
    )
    return r.json()


def test_bulk_history_delete(env):
    c, engine = env
    tokens = _register(c)
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    for i in range(3):
        assert (
            c.post("/conversations", headers=auth, json={"title": f"C{i}"}).status_code == 201
        )
    r = c.delete("/conversations", headers=auth)
    assert r.status_code == 200 and r.json()["deleted"] == 3
    assert c.get("/conversations", headers=auth).json()["conversations"] == []
    with Session(engine) as s:
        assert len(s.exec(select(Conversation)).all()) == 0


def test_retention_cleans_only_old_conversations(env, monkeypatch):
    c, engine = env
    tokens = _register(c)
    with Session(engine) as s:
        fresh = Conversation(user_id=tokens["user"]["id"], title="fresh")
        old = Conversation(
            user_id=tokens["user"]["id"],
            title="old",
            updated_at=datetime.now(UTC) - timedelta(days=10),
        )
        s.add(fresh)
        s.add(old)
        s.commit()
    monkeypatch.setattr(settings, "chat_retention_days", 5)
    assert conversation_cleanup.cleanup_expired_conversations() == 1
    with Session(engine) as s:
        titles = [x.title for x in s.exec(select(Conversation)).all()]
    assert titles == ["fresh"]
    monkeypatch.setattr(settings, "chat_retention_days", 0)


def test_webhook_signed_delivery_and_log(env, monkeypatch):
    c, engine = env
    monkeypatch.setattr(settings, "webhook_allow_private", True)
    tokens = _register(c)
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    server = HTTPServer(("127.0.0.1", 0), Capture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        r = c.post(
            "/automations/webhooks",
            headers=auth,
            json={"url": f"http://127.0.0.1:{port}/hook", "events": ["ticket.created"]},
        )
        assert r.status_code == 201, r.text
        hook = r.json()
        result = c.post(f"/automations/webhooks/{hook['id']}/test", headers=auth)
        assert result.status_code == 200 and result.json()["ok"], result.text
        assert captured["headers"]["X-Bohurupi-Event"] == "message.created"
        expected = "sha256=" + hmac.new(
            hook["secret"].encode(), captured["body"], hashlib.sha256
        ).hexdigest()
        assert captured["headers"]["X-Bohurupi-Signature"] == expected
        assert json.loads(captured["body"])["event"] == "message.created"
        with Session(engine) as s:
            rows = s.exec(select(WebhookDelivery)).all()
        assert len(rows) == 1 and rows[0].ok is True and rows[0].status_code == 200
    finally:
        server.shutdown()


def test_webhook_rejects_unknown_events(env):
    c, _ = env
    auth = {"Authorization": f"Bearer {_register(c)['access_token']}"}
    r = c.post(
        "/automations/webhooks",
        headers=auth,
        json={"url": "https://example.com/hook", "events": ["fake.event"]},
    )
    assert r.status_code == 400
