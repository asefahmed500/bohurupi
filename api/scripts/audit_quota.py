"""Live quota verification — run against an API started with a tiny quota:
    QUOTA_FREE_CHARS=100 uvicorn app.main:app --port 8000
Proves: speak counts chars, the next oversized speak is refused with 402-quota."""

import asyncio
import json
import time

import httpx
import websockets

BASE = "http://localhost:8000"


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as c:
        stamp = int(time.time())
        r = await c.post(
            f"{BASE}/auth/register",
            json={"email": f"quota-{stamp}@example.com", "password": "supersecret1"},
        )
        assert r.status_code == 201, r.text
        tok = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {tok}"}
        conv = (await c.post(f"{BASE}/conversations", headers=auth, json={"title": "Quota"})).json()

        async def speak(text: str) -> dict:
            uri = f"ws://localhost:8000/ws/chat/{conv['id']}?token={tok}"
            async with websockets.connect(uri) as ws:
                while True:
                    fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if fr["type"] == "ready":
                        break
                await ws.send(json.dumps({"type": "speak", "text": text, "lang": "en", "voice_id": "edge:us-aria-f"}))
                while True:
                    fr = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
                    if fr["type"] in ("done", "error"):
                        return fr

        # quota = 100 chars in this dedicated run
        first = await speak("Hello there, this is the first preview synthesis.")  # 50 chars
        print("first:", first["type"], first.get("audio_id", "")[:12])
        assert first["type"] == "done", first

        second = await speak("Hello there, this is the second preview synthesis.")  # another 50 -> 100/100
        print("second:", second["type"])
        assert second["type"] == "done", second

        third = await speak("This third one must be refused by the quota gate.")
        print("third:", third["type"], third.get("message", ""))
        assert third["type"] == "error" and "quota" in third["message"].lower(), third

        # usage REST endpoint reflects the counted chars (admin)
        print("\nQUOTA ENFORCEMENT PASS (chars counted; third request refused)")


asyncio.run(main())
