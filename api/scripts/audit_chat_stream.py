"""Full chat-pipeline E2E — LLM streaming -> sentence TTS -> persisted audio.

Runs a local OpenAI-compatible mock LLM (TEST TOOLING ONLY — the app itself
never ships mocks) and points the API at it via env, then exercises:
  ws chat -> status/text_token/sentence/audio frames -> done(message_id+audio_id)
  -> message + asset persisted, owned, downloadable
  -> respeak of the stored message in another voice
  -> history build excludes the live turn

Start the API as:
  ZAI_API_KEY=test-key ZAI_BASE_URL=http://localhost:9999/v4/ \
      uvicorn app.main:app --port 8000
"""

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import websockets

BASE = "http://localhost:8000"
REPLY = "Hello there friend. This is the second sentence for audio. Bangla test follows."

MOCK_PORT = 9999


class MockLLM(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length))
        msgs = body.get("messages", [])
        # translate request? (prompt mentions "Translate the following text")
        is_translate = any("Translate the following" in (m.get("content") or "") for m in msgs)
        target_lang = ""
        if is_translate:
            for m in msgs:
                c = m.get("content") or ""
                if "Translate the following" in c:
                    first_line = c.splitlines()[0]
                    target_lang = (
                        first_line.replace("Translate the following text into", "")
                        .strip()
                        .split(" (")[0]
                    )
        chunks = []
        if is_translate:
            text_out = f"{target_lang}· " + REPLY
        else:
            text_out = REPLY
        # stream in small word-chunks like a real LLM
        tokens = text_out.split(" ")
        for i, t in enumerate(tokens):
            piece = t + (" " if i < len(tokens) - 1 else "")
            chunks.append(piece)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for piece in chunks:
            payload = {
                "id": "mock-1",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()
        end = {
            "id": "mock-1",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        self.wfile.write(f"data: {json.dumps(end)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


async def drain(ws, timeout=180):
    frames = []
    while True:
        fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
        frames.append(fr)
        if fr["type"] in ("done", "error"):
            return frames


async def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), MockLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    ok = True
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(f"{BASE}/health")
            assert r.json()["llm"] is True, "API not started with the mock LLM env"

            stamp = int(time.time())
            r = await c.post(
                f"{BASE}/auth/register",
                json={"email": f"chat-{stamp}@example.com", "password": "supersecret1", "name": "Chat"},
            )
            tok = r.json()["access_token"]
            auth = {"Authorization": f"Bearer {tok}"}
            conv = (await c.post(f"{BASE}/conversations", headers=auth, json={"title": "Pipeline"})).json()
            conv_id = conv["id"]
            uri = f"ws://localhost:8000/ws/chat/{conv_id}?token={tok}"

            async with websockets.connect(uri) as ws:
                while True:
                    fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if fr["type"] == "ready":
                        break
                await ws.send(json.dumps({"type": "chat", "text": "Hi Bohurupi", "out_lang": "en", "voice_id": "edge:us-aria-f"}))
                frames = await drain(ws)

            types = [f["type"] for f in frames]
            done = frames[-1]
            # 1. streamed text tokens (translation may legitimately run when the
            # detected input language differs from the requested output language)
            tokens = "".join(f.get("v", "") for f in frames if f["type"] == "text_token")
            assert tokens.strip() in (REPLY, f"English· {REPLY}"), tokens
            print(f"[OK] text streamed ({tokens.count(' ')} tokens)")
            # 2. audio frames arrived
            audio = [f for f in frames if f["type"] == "audio"]
            assert len(audio) >= 3, types
            print(f"[OK] audio frames streamed ({len(audio)})")
            # 3. done carries message + audio ids
            assert done["type"] == "done" and done.get("message_id") and done.get("audio_id"), done
            print(f"[OK] done: message={done['message_id'][:8]} audio={done['audio_id'][:8]} lang={done['lang']}")

            # 4. persisted: conversation has user + assistant message with audio
            r = await c.get(f"{BASE}/conversations/{conv_id}", headers=auth)
            data = r.json()
            msgs = data["messages"]
            assert len(msgs) == 2, [m["role"] for m in msgs]
            assistant = next(m for m in msgs if m["role"] == "assistant")
            assert assistant["text"].strip() in (REPLY, f"English· {REPLY}")
            assert assistant["audio"], "assistant message has no audio asset"
            print(f"[OK] persisted: {len(msgs)} messages, audio asset {assistant['audio'][0]['id'][:8]}")

            # 5. asset is owned and downloadable
            r = await c.get(f"{BASE}/audio/{assistant['audio'][0]['id']}", headers=auth)
            assert r.status_code == 200 and r.content[:4] == b"RIFF"
            print(f"[OK] audio downloadable ({len(r.content)} bytes WAV)")

            # 6. respeak in another voice (no LLM) — cached path
            async with websockets.connect(uri) as ws:
                while True:
                    fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if fr["type"] == "ready":
                        break
                await ws.send(json.dumps({"type": "respeak", "message_id": done["message_id"], "voice_id": "kokoro:af-heart", "lang": "en"}))
                frames = await drain(ws)
            rdone = frames[-1]
            assert rdone["type"] == "done" and rdone.get("audio_id"), rdone
            print(f"[OK] respeak: engine={rdone['engine']} audio={rdone['audio_id'][:8]}")

            # 7. respeak cross-language uses translate (mock returns translated text)
            async with websockets.connect(uri) as ws:
                while True:
                    fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if fr["type"] == "ready":
                        break
                await ws.send(json.dumps({"type": "respeak", "message_id": done["message_id"], "voice_id": "edge:bd-nabanita-f", "lang": "bn"}))
                frames = await drain(ws)
            bdone = frames[-1]
            assert bdone["type"] == "done" and bdone.get("lang") == "bn", bdone
            tok_text = "".join(f.get("v", "") for f in frames if f["type"] == "text_token")
            assert tok_text.startswith("Bengali·"), tok_text[:120]
            print(f"[OK] cross-language respeak -> bn ({tok_text[:40]}...)")

            # 8. history now contains 3 assistant audio assets (2 respeaks + 1 original)
            r = await c.get(f"{BASE}/conversations/{conv_id}", headers=auth)
            msgs = r.json()["messages"]
            n_audio = sum(len(m.get("audio") or []) for m in msgs)
            assert n_audio == 3, n_audio
            print(f"[OK] history keeps all {n_audio} audio versions")

    except AssertionError as e:
        ok = False
        print(f"[FAIL] {e}")
    finally:
        server.shutdown()

    if ok:
        print("\nCHAT PIPELINE PASS")
    else:
        raise SystemExit(1)


asyncio.run(main())
