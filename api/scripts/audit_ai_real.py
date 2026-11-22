"""Full REAL-AI verification against the configured Z.AI GLM key.

Exercises: streaming chat, language detection, fixed-language translation,
re-speak (cached + LLM translation), voice->STT->chat round trip, persistence,
and latency. No mocks: every LLM/TTS/STT call hits the real configured stack.
"""

import asyncio
import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

import httpx
import websockets

BASE = "http://localhost:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


async def ws_frames(ws, payload: dict, timeout: float = 180) -> list[dict]:
    while True:
        fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        if fr["type"] == "ready":
            break
    t0 = time.monotonic()
    first_token = first_audio = None
    frames: list[dict] = []
    await ws.send(json.dumps(payload))
    while True:
        fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        frames.append(fr)
        if fr["type"] == "text_token" and first_token is None:
            first_token = (time.monotonic() - t0) * 1000
        if fr["type"] == "audio" and first_audio is None:
            first_audio = (time.monotonic() - t0) * 1000
        if fr["type"] in ("done", "error"):
            break
    meta = {"ttft_ms": first_token, "ttfa_ms": first_audio, "total_ms": (time.monotonic() - t0) * 1000}
    return frames, meta


async def main() -> None:
    async with httpx.AsyncClient(timeout=180) as c:
        health = (await c.get(f"{BASE}/health")).json()
        check("LLM configured (real Z.AI key)", health["llm"] is True, str(health["llm"]))

        stamp = int(time.time())
        r = await c.post(
            f"{BASE}/auth/register",
            json={"email": f"aireal-{stamp}@example.com", "password": "supersecret1", "name": "AI Real"},
        )
        check("register test user", r.status_code == 201, str(r.status_code))
        tok = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {tok}"}
        conv = (await c.post(f"{BASE}/conversations", headers=auth, json={"title": "Real AI audit"})).json()
        cid = conv["id"]
        uri = f"ws://localhost:8000/ws/chat/{cid}?token={tok}"

        # 1. real LLM chat (short English prompt)
        async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
            frames, meta = await ws_frames(
                ws,
                {"type": "chat", "text": "In one short sentence, say hello and name one colour.", "out_lang": "en", "voice_id": "edge:us-aria-f"},
            )
        done = frames[-1]
        tokens = "".join(f.get("v", "") for f in frames if f["type"] == "text_token")
        audio_frames = [f for f in frames if f["type"] == "audio"]
        check("chat: streamed real LLM tokens", len(tokens.strip()) > 10 and done["type"] == "done", f"text={tokens[:120]!r}")
        check("chat: streamed real TTS audio", len(audio_frames) >= 2, f"frames={len(audio_frames)}")
        check("chat: no error frame", not any(f["type"] == "error" for f in frames), str([f for f in frames if f["type"] == "error"])[:200])
        check("chat: done carries message+audio ids", bool(done.get("message_id") and done.get("audio_id")), f"msg={str(done.get('message_id'))[:8]} audio={str(done.get('audio_id'))[:8]}")
        print(f"    latency: first token {meta['ttft_ms']:.0f}ms · first audio {meta['ttfa_ms']:.0f}ms · total {meta['total_ms']:.0f}ms", flush=True)

        # 2. persistence + download
        data = (await c.get(f"{BASE}/conversations/{cid}", headers=auth)).json()
        msgs = data["messages"]
        check("chat: messages persisted", len(msgs) >= 2 and msgs[-1]["role"] == "assistant", f"count={len(msgs)}")
        check("chat: assistant audio persisted", any(float(a.get("duration", 0)) > 0 for m in msgs for a in (m.get("audio") or [])), str(msgs[-1].get("audio"))[:120])
        r = await c.get(f"{BASE}/audio/{done['audio_id']}", headers=auth)
        check("chat: WAV downloadable", r.status_code == 200 and r.content[:4] == b"RIFF", f"{len(r.content)} bytes")

        # 3. language detection (Bangla in -> Bangla out, auto)
        async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
            frames, meta = await ws_frames(
                ws,
                {"type": "chat", "text": "বাংলায় এক ছোট বাক্য বলুন যে আপনি ঠিক আছেন।", "out_lang": "auto", "voice_id": "edge:bd-nabanita-f"},
            )
        done_bn = frames[-1]
        bn_text = "".join(f.get("v", "") for f in frames if f["type"] == "text_token")
        has_bengali = any("\u0980" <= ch <= "\u09ff" for ch in bn_text)
        check("language ID: Bangla input -> Bangla reply", done_bn["type"] == "done" and has_bengali, f"lang={done_bn.get('lang')} text={bn_text[:90]!r}")

        # 4. fixed output language: English prompt -> Bangla reply (translate node)
        async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
            frames, meta = await ws_frames(
                ws,
                {"type": "chat", "text": "Say 'good morning' in one short sentence.", "out_lang": "bn", "voice_id": "edge:bd-nabanita-f"},
            )
        done_tr = frames[-1]
        tr_text = "".join(f.get("v", "") for f in frames if f["type"] == "text_token")
        check("translation: out_lang=bn produces done", done_tr["type"] == "done" and done_tr.get("lang") == "bn", f"lang={done_tr.get('lang')}")
        check("translation: no duplicated translation tokens", tr_text.count("good morning") <= 1 and tr_text.count("Good morning") <= 1, f"tokens={tr_text[:140]!r}")

        # 5. re-speak stored reply in another voice (no LLM)
        async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
            frames, meta = await ws_frames(
                ws,
                {"type": "respeak", "message_id": done["message_id"], "voice_id": "kokoro:af-heart", "lang": "en"},
            )
        check("re-speak: new voice, no LLM needed", frames[-1]["type"] == "done" and bool(frames[-1].get("audio_id")), f"engine={frames[-1].get('engine')}")

        # 6. cross-language re-speak (LLM translation -> Bangla TTS)
        async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
            frames, meta = await ws_frames(
                ws,
                {"type": "respeak", "message_id": done["message_id"], "voice_id": "edge:bd-nabanita-f", "lang": "bn"},
            )
        rsp = frames[-1]
        spoken = "".join(f.get("v", "") for f in frames if f["type"] == "text_token")
        check("cross-language re-speak: bn translation spoken", rsp["type"] == "done" and rsp.get("lang") == "bn" and bool(spoken.strip()), f"text={spoken[:90]!r}")

        # 7. voice -> STT -> chat (true voice-to-voice)
        speak_text = "Hello, this is a short speech recognition test."
        async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
            frames, meta = await ws_frames(
                ws,
                {"type": "speak", "text": speak_text, "lang": "en", "voice_id": "edge:us-aria-f"},
            )
        preview = frames[-1]
        if preview["type"] == "done" and preview.get("audio_id"):
            wav = await c.get(f"{BASE}/audio/{preview['audio_id']}", headers=auth)
            stt = await c.post(f"{BASE}/stt", headers=auth, files={"file": ("speech.wav", wav.content, "audio/wav")})
            transcript = stt.json().get("text", "") if stt.status_code == 200 else ""
            check("STT: real speech transcribed", stt.status_code == 200 and len(transcript.strip()) > 3, f"text={transcript[:100]!r}")
            if transcript.strip():
                async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
                    frames, meta = await ws_frames(
                        ws,
                        {"type": "chat", "text": transcript.strip(), "out_lang": "en", "voice_id": "edge:us-aria-f"},
                    )
                check("voice-to-voice: transcript -> LLM -> speech", frames[-1]["type"] == "done" and any(f["type"] == "audio" for f in frames), f"reply={frames[-1].get('text', '')[:80]!r}")
        else:
            check("STT: real speech transcribed", False, f"speak failed: {preview}")

        # 8. history/context retention: 3 audio versions + all messages
        data = (await c.get(f"{BASE}/conversations/{cid}", headers=auth)).json()
        n_audio = sum(len(m.get("audio") or []) for m in data["messages"])
        check("history: all replies + audio versions retained", len(data["messages"]) >= 6 and n_audio >= 4, f"messages={len(data['messages'])} audio={n_audio}")

        # 9. error path: LLM connectivity failure is surfaced honestly (invalid key in isolated client)
        # (covered by unit tests; no real key manipulation here to avoid touching your key)

    print("\n==== SUMMARY ====")
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL':<5} {name} {detail}")
    if any(not ok for _n, ok, _d in results):
        raise SystemExit(1)
    print("\nREAL AI FEATURES: ALL PASS")


asyncio.run(main())
