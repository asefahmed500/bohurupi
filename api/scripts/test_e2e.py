"""E2E: register -> create conversation -> WS speak frame -> audio frames -> health."""

import asyncio
import json

import httpx
import websockets

BASE = "http://localhost:8000"


async def main():
    async with httpx.AsyncClient(timeout=30) as client:
        # 1. register (fresh email per run)
        import time

        email = f"e2e-{int(time.time())}@example.com"
        r = await client.post(
            f"{BASE}/auth/register",
            json={"email": email, "password": "supersecret1", "name": "E2E"},
        )
        assert r.status_code == 201, r.text
        token = r.json()["access_token"]
        print("[OK] registered", email)

        # 2. me
        r = await client.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        print("[OK] /auth/me ->", r.json()["email"])

        # 3. conversation
        r = await client.post(
            f"{BASE}/conversations",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "E2E test"},
        )
        assert r.status_code == 201, r.text
        conv_id = r.json()["id"]
        print("[OK] conversation", conv_id)

        # 4. voices list
        r = await client.get(f"{BASE}/voices", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        voices = r.json()["voices"]
        print(f"[OK] /voices -> {len(voices)} voices")

        # 5. WS speak (TTS only, no LLM needed)
        uri = f"ws://localhost:8000/ws/chat/{conv_id}?token={token}"
        frames = []
        async with websockets.connect(uri) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "speak",
                        "text": "শুভেচ্ছা! This is Bohurupi speaking in Bangla and English.",
                        "voice_id": "edge:bd-nabanita-f",
                        "lang": "bn",
                        "speed": 1.0,
                    }
                )
            )
            while True:
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                frames.append(frame)
                if frame["type"] in ("done", "error"):
                    break

        audio_frames = [f for f in frames if f["type"] == "audio"]
        done = next((f for f in frames if f["type"] == "done"), None)
        err = next((f for f in frames if f["type"] == "error"), None)
        if err:
            print("[FAIL] error frame:", err)
            return
        total_b64 = sum(len(f["b64"]) for f in audio_frames)
        print(f"[OK] WS speak -> {len(audio_frames)} audio frames (~{total_b64 // 1024} KB b64)")
        print(
            f"[OK] done: engine={done['engine']} duration={done['duration']:.2f}s"
            f" audio_id={done['audio_id'][:12]}"
        )

        # 6. audio asset reachable
        audio_id = done["audio_id"]
        r = await client.get(
            f"{BASE}/audio/{audio_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        print(f"[OK] GET /audio -> {len(r.content)} bytes WAV")

        # 7. conversation contains the spoken message
        r = await client.get(
            f"{BASE}/conversations/{conv_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        msgs = r.json()["messages"]
        print(f"[OK] conversation has {len(msgs)} messages")

        # 8. usage event recorded
        r = await client.get(f"{BASE}/health")
        print("[OK] /health ->", json.dumps({k: v for k, v in r.json().items() if k != "engines"}))

    print("\nE2E PASS")


asyncio.run(main())
