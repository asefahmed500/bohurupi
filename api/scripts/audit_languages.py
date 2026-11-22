"""Verify the expanded language library end-to-end with real TTS/STT/LLM."""

import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import websockets

BASE = "http://localhost:8000"
NEW = ["af", "am", "az", "bg", "bs", "ca", "cs", "da", "el", "fi", "fil", "he", "hr", "hu",
       "is", "ka", "kk", "kn", "lt", "lv", "mk", "mr", "ms", "nb", "ne", "ro", "sk", "sq",
       "sr", "sv", "sw", "te", "th", "uk", "uz"]

ok_all = True


def check(name, ok, detail=""):
    global ok_all
    ok_all = ok_all and ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


async def main():
    async with httpx.AsyncClient(timeout=120) as c:
        langs = (await c.get(f"{BASE}/languages")).json()["languages"]
        codes = {item["code"] for item in langs}
        check("55 languages exposed", len(langs) == 55 and set(NEW) <= codes, f"count={len(langs)}")
        check("Hebrew flagged RTL", next(item for item in langs if item["code"] == "he")["rtl"] is True)

        stamp = int(__import__("time").time())
        r = await c.post(f"{BASE}/auth/register", json={"email": f"langs-{stamp}@example.com", "password": "supersecret1"})
        tok, auth = r.json()["access_token"], {"Authorization": f"Bearer {r.json()['access_token']}"}
        voices = (await c.get(f"{BASE}/voices", headers=auth)).json()["voices"]
        check("new presets seeded into existing DB", len(voices) >= 119, f"voices={len(voices)}")
        sv = [v for v in voices if "sv" in v["languages"]]
        he = [v for v in voices if "he" in v["languages"]]
        check("Swedish + Hebrew voices present", len(sv) == 2 and len(he) == 2, f"sv={len(sv)} he={len(he)}")

        cid = (await c.post(f"{BASE}/conversations", headers=auth, json={"title": "New languages"})).json()["id"]
        uri = f"ws://localhost:8000/ws/chat/{cid}?token={tok}"

        async def frame(payload, timeout=120):
            async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
                while True:
                    fr = json.loads(await asyncio.wait_for(ws.recv(), 15))
                    if fr["type"] == "ready":
                        break
                await ws.send(json.dumps(payload))
                frames = []
                while True:
                    fr = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                    frames.append(fr)
                    if fr["type"] in ("done", "error"):
                        return frames

        # real TTS in a brand-new language
        frames = await frame({"type": "speak", "text": "Hej! Det här är en röst på svenska.", "lang": "sv", "voice_id": "edge:se-sofie-f"})
        done = frames[-1]
        check("real TTS in Swedish", done["type"] == "done" and done.get("engine") == "edge" and sum(1 for f in frames if f["type"] == "audio") >= 2, f"engine={done.get('engine')}")

        # real LLM translation into a new language
        frames = await frame({"type": "chat", "text": "Say good morning in one short sentence.", "out_lang": "sv", "voice_id": "edge:se-sofie-f"})
        done2 = frames[-1]
        text = "".join(f.get("v", "") for f in frames if f["type"] == "text_token")
        check("real LLM reply translated to Swedish", done2["type"] == "done" and done2.get("lang") == "sv" and bool(text.strip()), f"text={text[:100]!r}")

        # local language detection for a new language
        from app.agent.graph import detect_language

        state = {"text": "Hej, hur mår du idag?", "in_lang": "", "out_lang": "auto", "reply": "", "reply_lang": "", "translations": {}}
        detected = detect_language(state)["in_lang"]
        check("lingua detects Swedish", detected == "sv", f"detected={detected}")

    print("\nEXPANDED LANGUAGES: ALL PASS" if ok_all else "\nFAILED")
    if not ok_all:
        raise SystemExit(1)


asyncio.run(main())
