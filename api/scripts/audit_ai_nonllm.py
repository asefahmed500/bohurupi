"""Verify the non-LLM AI stack with real models: Kokoro + Edge TTS,
faster-whisper STT, watermark metadata, local language ID, consent gate.
Also captures the real provider error message for a chat call (LLM blocked).
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import websockets

BASE = "http://localhost:8000"
ok_all = True


def check(name: str, ok: bool, detail: str = "") -> None:
    global ok_all
    ok_all = ok_all and ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


async def speak(c, auth, cid, tok, text, lang, voice):
    uri = f"ws://localhost:8000/ws/chat/{cid}?token={tok}"
    async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
        while True:
            fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if fr["type"] == "ready":
                break
        t0 = time.monotonic()
        await ws.send(json.dumps({"type": "speak", "text": text, "lang": lang, "voice_id": voice}))
        frames = []
        while True:
            fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
            frames.append(fr)
            if fr["type"] in ("done", "error"):
                break
        return frames, (time.monotonic() - t0) * 1000


async def main() -> None:
    async with httpx.AsyncClient(timeout=180) as c:
        h = (await c.get(f"{BASE}/health")).json()
        check("real LLM key configured", h["llm"] is True)
        check("real STT engine loaded", h["stt"] is True)

        stamp = int(time.time())
        r = await c.post(
            f"{BASE}/auth/register",
            json={"email": f"ainonllm-{stamp}@example.com", "password": "supersecret1"},
        )
        tok, auth = r.json()["access_token"], {"Authorization": f"Bearer {r.json()['access_token']}"}
        cid = (await c.post(f"{BASE}/conversations", headers=auth, json={"title": "AI non-LLM audit"})).json()["id"]

        # 1. Kokoro (local ONNX model) synthesis
        frames, ms = await speak(c, auth, cid, tok, "Hello, this is Kokoro speaking locally.", "en", "kokoro:af-heart")
        done = frames[-1]
        k_audio = sum(1 for f in frames if f["type"] == "audio")
        check("Kokoro TTS (real local model)", done["type"] == "done" and k_audio >= 2 and done.get("engine") == "kokoro", f"engine={done.get('engine')} frames={k_audio} {ms:.0f}ms")

        # 2. Edge TTS (network) synthesis in Bangla
        frames, ms = await speak(c, auth, cid, tok, "নমস্কার, আপনি কেমন আছেন?", "bn", "edge:bd-nabanita-f")
        done_edge = frames[-1]
        e_audio = sum(1 for f in frames if f["type"] == "audio")
        check("Edge TTS (real network engine, bn)", done_edge["type"] == "done" and e_audio >= 2 and done_edge.get("engine") == "edge", f"engine={done_edge.get('engine')} frames={e_audio} {ms:.0f}ms")

        # 3. Audio assets persisted with watermark metadata (studio previews
        # have message_id=NULL, so inspect the DB directly in this test harness)
        import sqlite3

        con = sqlite3.connect("bohurupi.db")
        rows = con.execute(
            "SELECT id, watermark_id FROM audioasset WHERE id IN (?, ?)",
            (done["audio_id"], done_edge["audio_id"]),
        ).fetchall()
        check("TTS assets persisted with watermark id", len(rows) == 2 and all(r[1] for r in rows), f"assets={len(rows)}")
        wav = await c.get(f"{BASE}/audio/{done_edge['audio_id']}", headers=auth)
        check("WAV download real bytes", wav.status_code == 200 and wav.content[:4] == b"RIFF", f"{len(wav.content)} bytes")

        # 4. faster-whisper STT on real synthesized speech
        stt = await c.post(f"{BASE}/stt", headers=auth, files={"file": ("bangla.wav", wav.content, "audio/wav")})
        transcript = stt.json().get("text", "") if stt.status_code == 200 else ""
        check("faster-whisper STT transcribes real speech", stt.status_code == 200 and len(transcript.strip()) > 2, f"text={transcript[:120]!r} lang={stt.json().get('language') if stt.status_code == 200 else ''}")

        # 5. Local language detection (lingua) — no LLM needed
        from app.agent.graph import detect_language

        langs = [
            detect_language({"text": "আমি ভালো আছি", "in_lang": "", "out_lang": "auto", "reply": "", "reply_lang": "", "translations": {}}).get("in_lang"),
            detect_language({"text": "This is English text", "in_lang": "", "out_lang": "auto", "reply": "", "reply_lang": "", "translations": {}}).get("in_lang"),
        ]
        check("lingua language ID (bn/en)", langs == ["bn", "en"], str(langs))

        # 6. Consent gate (no LLM)
        phrase = (await c.get(f"{BASE}/voices/consent-phrase", params={"lang": "en"})).json()["phrase"]
        import io
        import wave

        import numpy as np

        n = 16000 * 12
        t = np.linspace(0, 12, n, endpoint=False)
        x = (0.25 * np.sin(2 * np.pi * 220 * t)).astype("float32")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes((x * 32767).astype("<i2").tobytes())
        sample = buf.getvalue()
        bad = await c.post(
            f"{BASE}/voices/clone", headers=auth,
            data={"name": "X", "consent": "true", "consent_lang": "en", "consent_phrase_text": "wrong", "sample_lang": "en"},
            files={"sample": ("s.wav", sample, "audio/wav"), "consent_audio": ("c.wav", sample, "audio/wav")},
        )
        check("consent gate rejects wrong phrase", bad.status_code == 400, str(bad.status_code))
        good = await c.post(
            f"{BASE}/voices/clone", headers=auth,
            data={"name": "Real clone", "consent": "true", "consent_lang": "en", "consent_phrase_text": phrase, "sample_lang": "en"},
            files={"sample": ("s.wav", sample, "audio/wav"), "consent_audio": ("c.wav", sample, "audio/wav")},
        )
        check("consent gate accepts valid sample", good.status_code == 201 and good.json()["status"] == "moderation", str(good.status_code))

        # 7. Capture the real provider error for a chat call (LLM account balance)
        uri = f"ws://localhost:8000/ws/chat/{cid}?token={tok}"
        async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
            while True:
                fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if fr["type"] == "ready":
                    break
            await ws.send(json.dumps({"type": "chat", "text": "Hi", "out_lang": "en"}))
            while True:
                fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
                if fr["type"] in ("error", "done"):
                    break
        check("LLM-call failure surfaced (not fake success)", fr["type"] == "error", f"message={fr.get('message', '')[:160]!r}")

    print("\n==== SUMMARY ====")
    if ok_all:
        print("NON-LLM AI STACK: ALL PASS")
    else:
        raise SystemExit(1)


asyncio.run(main())
