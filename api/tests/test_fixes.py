"""Regression tests for the audit fixes: quotas, audio ownership, admin users,
engine persistence, history dedup, WS clamping."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.config import settings
from app.db import models  # noqa: F401
from app.db.models import AudioAsset, Conversation, EngineState, Message
from app.db.session import get_session
from app.engines.base import AudioChunk, TTSEngine, VoiceInfo
from app.engines.registry import Registry
from app.main import create_app


class FakeEngine(TTSEngine):
    """Offline TTS engine for tests — tiny PCM chunk per request."""

    name = "fake"
    quality_rank = 1

    def healthy(self):
        return True

    def supports(self, lang):
        return True

    def list_voices(self):
        return [VoiceInfo(id="fake:v1", name="Fake", engine="fake", languages=["en"])]

    async def synthesize(self, text, lang, voice_id, speed=1.0, style=None):
        yield AudioChunk(pcm=b"\x00\x01" * 800, sample_rate=16000)


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

    # swap the live registry (kokoro/edge) for a deterministic offline engine
    registry = Registry([FakeEngine()], persist=False)
    monkeypatch.setattr("app.services.tts.get_registry", lambda: registry)
    monkeypatch.setattr(settings, "quota_free_chars", 40)

    return TestClient(app), registry, engine


def _register(client: TestClient, email: str) -> dict:
    r = client.post("/auth/register", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 201, r.text
    return r.json()


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _ws_speak(client: TestClient, conv_id: str, token: str, payload: dict) -> list[dict]:
    frames = []
    with client.websocket_connect(f"/ws/chat/{conv_id}?token={token}") as ws:
        while True:
            fr = json.loads(ws.receive_text())
            if fr["type"] == "ready":
                break
        ws.send_text(json.dumps({"type": "speak", **payload}))
        while True:
            fr = json.loads(ws.receive_text())
            frames.append(fr)
            if fr["type"] in ("done", "error"):
                break
    return frames


def test_quota_enforced_and_counted(env):
    c, _registry, _engine = env
    tokens = _register(c, "quota@example.com")
    tok = tokens["access_token"]
    conv = c.post("/conversations", headers=_auth(tokens), json={"title": "Q"}).json()

    # free quota patched to 40 chars: a 30-char speak fits, the next must be refused
    frames = _ws_speak(
        c, conv["id"], tok,
        {"text": "x" * 30, "lang": "en", "voice_id": "fake:v1"},
    )
    assert frames[-1]["type"] == "done", frames
    assert frames[-1].get("audio_id")

    frames2 = _ws_speak(
        c, conv["id"], tok,
        {"text": "x" * 30, "lang": "en", "voice_id": "fake:v1"},
    )
    assert frames2[-1]["type"] == "error", frames2
    assert "quota" in frames2[-1]["message"].lower()


def test_audio_ownership_idor(env):
    c, _registry, engine = env
    a = _register(c, "owner@example.com")
    b = _register(c, "other@example.com")
    conv = c.post("/conversations", headers=_auth(a), json={"title": "O"}).json()
    frames = _ws_speak(
        c, conv["id"], a["access_token"],
        {"text": "hello there", "lang": "en", "voice_id": "fake:v1"},
    )
    audio_id = frames[-1]["audio_id"]

    # other user: denied
    r = c.get(f"/audio/{audio_id}", headers=_auth(b))
    assert r.status_code == 404
    # owner: allowed, real WAV
    r = c.get(f"/audio/{audio_id}", headers=_auth(a))
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    # asset row carries the owner
    with Session(engine) as s:
        asset = s.get(AudioAsset, audio_id)
        assert asset is not None
        assert asset.user_id == a["user"]["id"]


def test_persist_reply_audio_unit(env):
    c, _registry, engine = env
    tokens = _register(c, "persist@example.com")
    conv = c.post("/conversations", headers=_auth(tokens), json={"title": "P"}).json()

    with Session(engine) as s:
        m = Message(conversation_id=conv["id"], role="assistant", text="reply text")
        s.add(m)
        s.commit()
        s.refresh(m)
        msg_id = m.id

    from app.services.chat import _persist_reply_audio

    with Session(engine) as s:
        audio_id = _persist_reply_audio(
            s, msg_id, tokens["user"]["id"], [(b"\x00\x01" * 1600, 16000)], "en"
        )
        assert audio_id
        asset = s.get(AudioAsset, audio_id)
        assert asset.user_id == tokens["user"]["id"]
        assert asset.message_id == msg_id


def test_build_messages_excludes_live_turn(env):
    from app.services.chat import _build_messages

    c, _registry, engine = env
    tokens = _register(c, "hist@example.com")
    conv = c.post("/conversations", headers=_auth(tokens), json={"title": "H"}).json()

    with Session(engine) as s:
        live = Message(conversation_id=conv["id"], role="user", text="current question")
        s.add(live)
        s.commit()
        s.refresh(live)
        conv_row = s.get(Conversation, conv["id"])
        msgs = _build_messages(
            s, conv_row, "current question", "auto", exclude_message_id=live.id
        )
    human = [m for m in msgs if type(m).__name__ == "HumanMessage"]
    assert len(human) == 1  # the live turn appears exactly once
    assert human[0].content == "current question"


def test_admin_user_management(env):
    c, _registry, _engine = env
    u = _register(c, "member@example.com")
    member_id = u["user"]["id"]

    # non-admin blocked
    r = c.patch(f"/admin/users/{member_id}", headers=_auth(u), json={"role": "admin"})
    assert r.status_code in (401, 403)

    # register the ADMIN_EMAIL user -> admin
    old = settings.admin_email
    settings.admin_email = "boss@example.com"
    boss = _register(c, "boss@example.com")
    settings.admin_email = old
    assert boss["user"]["role"] == "admin"

    r = c.patch(
        f"/admin/users/{member_id}",
        headers=_auth(boss),
        json={"plan": "pro", "role": "admin", "is_active": False},
    )
    assert r.status_code == 200
    assert r.json()["plan"] == "pro"
    assert r.json()["role"] == "admin"
    assert r.json()["is_active"] is False

    # disabled user cannot log in
    r = c.post("/auth/login", json={"email": "member@example.com", "password": "supersecret1"})
    assert r.status_code == 403

    # invalid values rejected
    r = c.patch(f"/admin/users/{member_id}", headers=_auth(boss), json={"plan": "gold"})
    assert r.status_code == 400
    r = c.patch(f"/admin/users/{member_id}", headers=_auth(boss), json={"role": "superuser"})
    assert r.status_code == 400

    # admin cannot disable or demote themselves
    boss_id = boss["user"]["id"]
    r = c.patch(f"/admin/users/{boss_id}", headers=_auth(boss), json={"is_active": False})
    assert r.status_code == 400
    r = c.patch(f"/admin/users/{boss_id}", headers=_auth(boss), json={"role": "user"})
    assert r.status_code == 400

    # unknown user 404
    r = c.patch("/admin/users/missing", headers=_auth(boss), json={"plan": "pro"})
    assert r.status_code == 404

    # re-enable -> login works again
    r = c.patch(f"/admin/users/{member_id}", headers=_auth(boss), json={"is_active": True})
    assert r.status_code == 200
    r = c.post("/auth/login", json={"email": "member@example.com", "password": "supersecret1"})
    assert r.status_code == 200


def test_engine_toggle_persists(env, monkeypatch):
    c, registry, engine = env
    # registry persistence uses the global engine — point it at the test engine
    monkeypatch.setattr("app.db.session.engine", engine, raising=False)
    registry = Registry([FakeEngine()])  # persist=True: this is what we're testing

    registry.set_enabled("fake", False)
    with Session(engine) as s:
        row = s.get(EngineState, "fake")
        assert row is not None and row.enabled is False

    # a brand-new registry loads the persisted state
    fresh = Registry([FakeEngine()])
    assert fresh.is_enabled("fake") is False
    registry.set_enabled("fake", True)
    with Session(engine) as s:
        row = s.get(EngineState, "fake")
        assert row.enabled is True


def test_ws_frame_values_clamped(env):
    c, _registry, _engine = env
    tokens = _register(c, "clamp@example.com")
    tok = tokens["access_token"]
    conv = c.post("/conversations", headers=_auth(tokens), json={"title": "C"}).json()
    # absurd speed/pitch must not crash synthesis
    frames = _ws_speak(
        c, conv["id"], tok,
        {
            "text": "clamped",
            "lang": "en",
            "voice_id": "fake:v1",
            "speed": 100,
            "pitch_semitones": 99,
        },
    )
    assert frames[-1]["type"] == "done"


def test_health_reports_oauth_flag(env):
    c, _registry, _engine = env
    r = c.get("/health")
    assert r.status_code == 200
    assert "oauth_google" in r.json()
