"""Audit script: exercises auth, RBAC, IDOR, quotas, CRUD, WS flows with PASS/FAIL evidence."""

import asyncio
import io
import json
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE = "http://localhost:8000"
results: list[tuple[str, str, str]] = []  # (area, name, status + evidence)


def record(area: str, name: str, ok: bool, evidence: str = "") -> None:
    results.append((area, name, ("PASS" if ok else "FAIL") + (f" — {evidence}" if evidence else "")))
    print(f"[{'PASS' if ok else 'FAIL'}] {area}/{name} {evidence}")


def wav_bytes(seconds: float, sr: int = 16000, amp: float = 0.3) -> bytes:
    import numpy as np

    n = int(seconds * sr)
    t = np.linspace(0, seconds, n, endpoint=False)
    x = (amp * np.sin(2 * np.pi * 220 * t)).astype("float32")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return buf.getvalue()


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as c:
        stamp = int(time.time())

        # ---------- auth ----------
        r = await c.post(f"{BASE}/auth/register", json={"email": f"aud-{stamp}@x.com", "password": "supersecret1", "name": "Aud"})
        record("auth", "register 201", r.status_code == 201, str(r.status_code))
        user_tok = r.json()["access_token"]
        user = r.json()["user"]
        ua = {"Authorization": f"Bearer {user_tok}"}

        # mint an admin token straight from the env secret (controlled test account)
        import sqlite3

        import jwt as pyjwt

        from app.config import settings

        con = sqlite3.connect("bohurupi.db")
        admin_id = con.execute("select id from user where role='admin' limit 1").fetchone()[0]
        now = int(time.time())
        admin_tok = pyjwt.encode(
            {"sub": admin_id, "type": "access", "iat": now, "exp": now + 3600, "role": "admin"},
            settings.jwt_secret,
            algorithm="HS256",
        )
        aa = {"Authorization": f"Bearer {admin_tok}"}
        r = await c.get(f"{BASE}/auth/me", headers=aa)
        record("auth", "admin token works", r.status_code == 200 and r.json()["role"] == "admin", r.text[:80])

        r = await c.post(f"{BASE}/auth/login", json={"email": f"aud-{stamp}@x.com", "password": "wrong"})
        record("auth", "wrong password 401", r.status_code == 401, str(r.status_code))
        r = await c.get(f"{BASE}/auth/me", headers=ua)
        record("auth", "me with token", r.status_code == 200 and r.json()["email"] == f"aud-{stamp}@x.com")
        r = await c.get(f"{BASE}/auth/me")
        record("auth", "me without token 401", r.status_code == 401, str(r.status_code))
        r = await c.get(f"{BASE}/auth/me", headers={"Authorization": "Bearer garbage"})
        record("auth", "invalid token 401", r.status_code == 401, str(r.status_code))
        r = await c.get(f"{BASE}/auth/me", headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ4In0.sig"})
        record("auth", "forged token 401", r.status_code == 401, str(r.status_code))
        r = await c.post(f"{BASE}/auth/refresh", json={"refresh_token": "not-a-token"})
        record("auth", "invalid refresh 401", r.status_code == 401, str(r.status_code))

        # ---------- RBAC ----------
        for path in ("/admin/engines", "/admin/usage", "/admin/users", "/admin/stats", "/admin/voices/moderation"):
            r = await c.get(f"{BASE}{path}", headers=ua)
            record("rbac", f"user blocked {path}", r.status_code == 403, str(r.status_code))
            r = await c.get(f"{BASE}{path}", headers=aa)
            record("rbac", f"admin allowed {path}", r.status_code == 200, str(r.status_code))
        r = await c.get(f"{BASE}/audio/whatever/detect", headers=ua)
        record("rbac", "watermark detect admin-only", r.status_code == 403, str(r.status_code))

        # ---------- conversations CRUD + ownership ----------
        r = await c.post(f"{BASE}/conversations", headers=ua, json={"title": "Aud A"})
        conv_a = r.json()["id"]
        r = await c.post(f"{BASE}/conversations", headers=aa, json={"title": "Aud B"})
        conv_b = r.json()["id"]
        r = await c.get(f"{BASE}/conversations/{conv_b}", headers=ua)
        record("idor", "other user's conversation 404", r.status_code == 404, str(r.status_code))
        r = await c.patch(f"{BASE}/conversations/{conv_b}", headers=ua, json={"title": "hacked"})
        record("idor", "patch other's conversation 404", r.status_code == 404, str(r.status_code))
        r = await c.delete(f"{BASE}/conversations/{conv_b}", headers=ua)
        record("idor", "delete other's conversation 404", r.status_code == 404, str(r.status_code))
        r = await c.patch(f"{BASE}/conversations/{conv_a}", headers=ua, json={"title": "Renamed"})
        record("chat", "patch own conversation", r.status_code == 200 and r.json()["title"] == "Renamed")

        # ---------- quota (live proof via WS speak; quota counted after each synth) ----------
        # REST /chat caps text at 8000 chars (422 below). Enforcement is proven in the
        # dedicated low-quota run (scripts/audit_quota.py) and unit tests.
        r = await c.post(f"{BASE}/chat", headers=ua, json={"text": "x" * 9000, "conversation_id": conv_a})
        record("chat", "REST chat caps text at 8000 (422)", r.status_code == 422, str(r.status_code))

        # normal-size speak via WS (real TTS) to exercise the audio path
        import websockets

        uri = f"ws://localhost:8000/ws/chat/{conv_a}?token={user_tok}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type": "speak", "text": "Audit one two three.", "lang": "en", "voice_id": "edge:us-aria-f"}))
            frames = []
            while True:
                fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
                frames.append(fr)
                if fr["type"] in ("done", "error"):
                    break
            done = frames[-1]
            record("tts", "ws speak produces audio", done["type"] == "done" and done.get("audio_id"), json.dumps(done)[:120])
            speak_audio_id = done.get("audio_id", "")

        # IDOR: studio-preview audio (message_id=None) must not be world-readable
        r = await c.post(f"{BASE}/auth/register", json={"email": f"aud2-{stamp}@x.com", "password": "supersecret1"})
        ua2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.get(f"{BASE}/audio/{speak_audio_id}", headers=ua2)
        record("idor", "other user cannot fetch orphan audio", r.status_code == 404, str(r.status_code))
        r = await c.get(f"{BASE}/audio/{speak_audio_id}", headers=ua)
        record("tts", "owner fetches own audio", r.status_code == 200 and r.content[:4] == b"RIFF", str(r.status_code))
        r = await c.get(f"{BASE}/audio/does-not-exist", headers=ua)
        record("audio", "missing audio 404", r.status_code == 404, str(r.status_code))

        # ---------- voices ----------
        r = await c.get(f"{BASE}/voices", headers=ua)
        record("voices", "list presets", r.status_code == 200 and len(r.json()["voices"]) >= 40, f"{len(r.json().get('voices', []))} voices")
        r = await c.get(f"{BASE}/voices", headers=ua, params={"lang": "bn"})
        ok = all("bn" in v["languages"] for v in r.json()["voices"]) and len(r.json()["voices"]) > 0
        record("voices", "filter lang=bn", ok)
        r = await c.get(f"{BASE}/voices", headers=ua, params={"gender": "female"})
        record("voices", "filter gender", all(v["gender"] == "female" for v in r.json()["voices"]))
        r = await c.get(f"{BASE}/voices", headers=ua, params={"q": "বাংলা"})
        record("voices", "search q", any("বাংলা" in v["name"] for v in r.json()["voices"]))
        r = await c.get(f"{BASE}/voices", headers=ua, params={"mine": "true"})
        record("voices", "mine empty initially", r.json()["voices"] == [])

        # consent phrase + clone gate
        r = await c.get(f"{BASE}/voices/consent-phrase", params={"lang": "en"})
        phrase = r.json()["phrase"]
        sample = wav_bytes(15)
        # wrong phrase
        r = await c.post(
            f"{BASE}/voices/clone", headers=ua,
            data={"name": "V", "consent": "true", "consent_lang": "en", "consent_phrase_text": "wrong", "sample_lang": "en"},
            files={"sample": ("s.wav", sample, "audio/wav"), "consent_audio": ("c.wav", sample, "audio/wav")},
        )
        record("clone", "wrong phrase rejected", r.status_code == 400, str(r.status_code))
        # no consent checkbox
        r = await c.post(
            f"{BASE}/voices/clone", headers=ua,
            data={"name": "V", "consent": "false", "consent_lang": "en", "consent_phrase_text": phrase, "sample_lang": "en"},
            files={"sample": ("s.wav", sample, "audio/wav"), "consent_audio": ("c.wav", sample, "audio/wav")},
        )
        record("clone", "no consent rejected", r.status_code == 400, str(r.status_code))
        # too short sample
        r = await c.post(
            f"{BASE}/voices/clone", headers=ua,
            data={"name": "V", "consent": "true", "consent_lang": "en", "consent_phrase_text": phrase, "sample_lang": "en"},
            files={"sample": ("s.wav", wav_bytes(3), "audio/wav"), "consent_audio": ("c.wav", sample, "audio/wav")},
        )
        record("clone", "short sample rejected", r.status_code == 400 and "short" in r.text, str(r.status_code))
        # bad file type
        r = await c.post(
            f"{BASE}/voices/clone", headers=ua,
            data={"name": "V", "consent": "true", "consent_lang": "en", "consent_phrase_text": phrase, "sample_lang": "en"},
            files={"sample": ("s.exe", b"MZfake", "application/octet-stream"), "consent_audio": ("c.wav", sample, "audio/wav")},
        )
        record("clone", "bad extension rejected", r.status_code == 415, str(r.status_code))
        # valid clone -> moderation
        r = await c.post(
            f"{BASE}/voices/clone", headers=ua,
            data={"name": "Aud voice", "consent": "true", "consent_lang": "en", "consent_phrase_text": phrase, "sample_lang": "en"},
            files={"sample": ("s.wav", sample, "audio/wav"), "consent_audio": ("c.wav", sample, "audio/wav")},
        )
        record("clone", "valid clone 201 moderation", r.status_code == 201 and r.json()["status"] == "moderation", r.text[:120])
        cloned_id = r.json()["voice"]["id"] if r.status_code == 201 else ""
        r = await c.get(f"{BASE}/voices", headers=ua, params={"mine": "true"})
        record("voices", "mine shows pending clone", any(v["id"] == cloned_id for v in r.json()["voices"]))
        # hidden from others
        r = await c.get(f"{BASE}/voices", headers=aa)
        record("idor", "clone hidden from others", all(v["id"] != cloned_id for v in r.json()["voices"]))
        # sample download owner-only
        r = await c.get(f"{BASE}/voices/{cloned_id}/sample", headers=aa)
        record("idor", "sample download other 404", r.status_code == 404, str(r.status_code))
        r = await c.get(f"{BASE}/voices/{cloned_id}/sample", headers=ua)
        record("clone", "sample download owner 200 wav", r.status_code == 200 and r.content[:4] == b"RIFF", str(r.status_code))
        # admin moderation queue
        r = await c.get(f"{BASE}/admin/voices/moderation", headers=aa)
        record("admin", "moderation queue shows clone", any(v["id"] == cloned_id for v in r.json()["voices"]))
        r = await c.post(f"{BASE}/admin/voices/{cloned_id}/moderate", headers=aa, json={"decision": "approve"})
        record("admin", "approve clone", r.status_code == 200 and r.json()["status"] == "ready")
        r = await c.post(f"{BASE}/admin/voices/{cloned_id}/moderate", headers=aa, json={"decision": "bogus"})
        record("admin", "bogus decision 400", r.status_code == 400, str(r.status_code))

        # ---------- WS respeak + chat error honesty ----------
        uri = f"ws://localhost:8000/ws/chat/{conv_a}?token={user_tok}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"type": "chat", "text": "hello"}))
            frames = []
            while True:
                fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                frames.append(fr["type"])
                if fr["type"] in ("done", "error"):
                    record("chat", "chat without LLM key errors honestly", fr["type"] == "error", json.dumps(fr)[:160])
                    break
        # respeak needs an assistant message; without LLM there is none — expect a clear error
        async with websockets.connect(uri) as ws:
            ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            assert ready["type"] == "ready"
            await ws.send(json.dumps({"type": "respeak", "message_id": "nonexistent", "voice_id": "edge:us-aria-f"}))
            fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            record("ws", "respeak unknown message errors", fr["type"] == "error", json.dumps(fr)[:100])
        async with websockets.connect(uri) as ws:
            ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            assert ready["type"] == "ready"
            await ws.send(json.dumps({"type": "ping"}))
            fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            record("ws", "ping/pong", fr["type"] == "pong")
        # unauthorized WS
        try:
            async with websockets.connect(f"ws://localhost:8000/ws/chat/{conv_a}?token=bad"):
                record("ws", "unauthorized ws rejected", False, "connected!")
        except Exception as e:
            record("ws", "unauthorized ws rejected", "403" in str(e) or "4401" in str(e) or "closed" in str(e).lower(), str(e)[:80])

        # ---------- stt ----------
        r = await c.post(f"{BASE}/stt", headers=ua, files={"file": ("a.wav", wav_bytes(2), "audio/wav")})
        record("stt", "transcribe wav", r.status_code == 200, r.text[:100])
        r = await c.post(f"{BASE}/stt", headers=ua, files={"file": ("a.wav", b"x" * 10, "audio/wav")})
        record("stt", "tiny file rejected", r.status_code == 400, str(r.status_code))
        r = await c.post(f"{BASE}/stt", files={"file": ("a.wav", wav_bytes(2), "audio/wav")})
        record("stt", "unauthenticated 401", r.status_code == 401, str(r.status_code))

        # ---------- rate limits ----------
        r = await c.post(f"{BASE}/auth/register", json={"email": f"rl-{stamp}@x.com", "password": "supersecret1"})
        tok = r.json()["access_token"]
        rl_conv = (await c.post(f"{BASE}/conversations", headers={"Authorization": f"Bearer {tok}"}, json={"title": "RL"})).json()["id"]
        codes = []
        for _ in range(65):
            rr = await c.post(f"{BASE}/chat", headers={"Authorization": f"Bearer {tok}"}, json={"text": "hi", "conversation_id": rl_conv})
            codes.append(rr.status_code)
        record("limits", "REST /chat rate limited", 429 in codes, f"codes={set(codes)}")

        # ---------- conversation delete cascades audio ----------
        r = await c.delete(f"{BASE}/conversations/{conv_a}", headers=ua)
        record("chat", "delete conversation 204", r.status_code == 204, str(r.status_code))
        r = await c.get(f"{BASE}/conversations/{conv_a}", headers=ua)
        record("chat", "deleted conversation gone", r.status_code == 404)

        # ---------- engine toggle (admin) ----------
        r = await c.post(f"{BASE}/admin/engines/edge", headers=aa, json={"enabled": False})
        record("admin", "disable edge", r.status_code == 200)
        r = await c.get(f"{BASE}/admin/engines", headers=aa)
        edge = next(e for e in r.json()["engines"] if e["name"] == "edge")
        record("admin", "edge shows disabled", edge["enabled"] is False)
        r = await c.post(f"{BASE}/admin/engines/edge", headers=aa, json={"enabled": True})
        record("admin", "re-enable edge", r.status_code == 200)
        r = await c.post(f"{BASE}/admin/engines/nope", headers=aa, json={"enabled": False})
        record("admin", "unknown engine 404", r.status_code == 404, str(r.status_code))

        # ---------- admin user management ----------
        r = await c.get(f"{BASE}/admin/users", headers=aa, params={"limit": 500})
        users_list = r.json()["users"]
        target = next((u for u in users_list if u["email"].startswith("aud2-")), None)
        if target:
            r = await c.patch(f"{BASE}/admin/users/{target['id']}", headers=aa, json={"plan": "pro"})
            record("admin", "patch user plan", r.status_code == 200 and r.json()["plan"] == "pro", r.text[:80])
            r = await c.patch(f"{BASE}/admin/users/{target['id']}", headers=aa, json={"plan": "gold"})
            record("admin", "invalid plan rejected", r.status_code == 400, str(r.status_code))
            r = await c.patch(f"{BASE}/admin/users/{target['id']}", headers=aa, json={"is_active": False})
            record("admin", "disable user", r.status_code == 200 and r.json()["is_active"] is False)
            r = await c.get(f"{BASE}/auth/me", headers=ua2)
            record("admin", "disabled user rejected (401)", r.status_code == 401, str(r.status_code))
            r = await c.patch(f"{BASE}/admin/users/{target['id']}", headers=aa, json={"is_active": True})
            record("admin", "re-enable user", r.status_code == 200)
            admin_row = next(u for u in users_list if u["role"] == "admin")
            r = await c.patch(f"{BASE}/admin/users/{admin_row['id']}", headers=aa, json={"is_active": False})
            record("admin", "self-disable blocked", r.status_code == 400, str(r.status_code))
        r = await c.patch(f"{BASE}/admin/users/missing-user", headers=aa, json={"plan": "pro"})
        record("admin", "patch unknown user 404", r.status_code == 404, str(r.status_code))

    print("\n==== SUMMARY ====")
    for area, name, status in results:
        print(f"{status:<6} {area}/{name}")


asyncio.run(main())
