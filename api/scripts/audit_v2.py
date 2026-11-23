"""Real E2E for the v2 expansion: support agent (RAG+tickets), MCP server &
client tools, voice training & daily self-improvement."""

import asyncio
import io
import json
import sqlite3
import sys
import time
import wave
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import jwt as pyjwt
import numpy as np
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE = "http://localhost:8000"
MCP_KEY = "bohurupi-mcp-local-key"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def wav_bytes(seconds: float = 12) -> bytes:
    n = int(seconds * 16000)
    t = np.linspace(0, seconds, n, endpoint=False)
    x = (0.25 * np.sin(2 * np.pi * 180 * t)).astype("float32")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return buf.getvalue()


async def mcp_call(url: str, headers: dict, fn) -> object:
    async with httpx.AsyncClient(headers=headers, timeout=60) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                return await fn(session)


async def main() -> None:
    async with httpx.AsyncClient(timeout=180) as c:
        health = (await c.get(f"{BASE}/health")).json()
        check("API healthy with LLM", health["ok"] and health["llm"], str(health["llm"]))

        # admin token (test harness only — signed with local dev secret)
        env = Path(__file__).resolve().parent.parent / ".env"
        secret = next(
            line.split("=", 1)[1].strip()
            for line in env.read_text(encoding="utf-8").splitlines()
            if line.startswith("JWT_SECRET=")
        )
        con = sqlite3.connect("bohurupi.db")
        admin_id = con.execute("SELECT id FROM user WHERE role='admin' LIMIT 1").fetchone()[0]
        now = int(time.time())
        token = pyjwt.encode(
            {"sub": admin_id, "type": "access", "iat": now, "exp": now + 3600, "role": "admin"},
            secret,
            algorithm="HS256",
        )
        admin = {"Authorization": f"Bearer {token}"}

        # ---------- 1. support business + knowledge ----------
        slug = f"acme-{int(time.time())}"
        r = await c.post(f"{BASE}/support/businesses", headers=admin, json={
            "name": "Acme Support", "slug": slug, "languages": ["en", "bn"],
            "system_prompt": "You are Acme's support agent. Only use the knowledge provided.",
        })
        check("create business (admin)", r.status_code == 201, str(r.status_code))
        doc = await c.post(f"{BASE}/support/businesses/{slug}/documents", headers=admin, json={
            "title": "Refund policy",
            "content": "Acme refunds any unused product within 30 days of purchase. "
                       "To request a refund, email refunds@acme.example with your order number. "
                       "Shipping fees are not refundable. Escalate to a human for damaged items.",
            "source": "policy.md",
        })
        check("ingest knowledge document", doc.status_code == 201 and doc.json()["chunks"] >= 1, str(doc.json()))
        search = await c.get(f"{BASE}/support/businesses/{slug}/search", headers=admin, params={"q": "How long do I have to return an item?"})
        check("real RAG retrieval (hashed TF-IDF)", search.status_code == 200 and len(search.json()["hits"]) >= 1, f"hits={len(search.json().get('hits', []))} score={search.json().get('hits', [{}])[0].get('score') if search.json().get('hits') else ''}")

        chat = await c.post(f"{BASE}/support/chat", json={
            "business_slug": slug,
            "message": "How many days do I have to request a refund?",
            "email": "customer@example.com",
        })
        reply = chat.json().get("reply", "") if chat.status_code == 200 else chat.text[:200]
        check("support chat grounded in knowledge (real LLM)", chat.status_code == 200 and "30" in reply, f"reply={reply[:160]!r}")

        esc = await c.post(f"{BASE}/support/chat", json={
            "business_slug": slug,
            "message": "My item arrived damaged. I want to speak to a human agent now.",
            "email": "angry@example.com",
        })
        ticket_id = esc.json().get("ticket_id") if esc.status_code == 200 else None
        check("LLM escalation creates real ticket", bool(ticket_id), f"ticket={str(ticket_id)[:8]} reply={esc.json().get('reply','')[:80]!r}")
        tickets = await c.get(f"{BASE}/support/tickets", headers=admin)
        check("ticket visible in admin queue", any(t["id"] == ticket_id for t in tickets.json()["tickets"]), f"count={len(tickets.json()['tickets'])}")
        if ticket_id:
            patched = await c.patch(f"{BASE}/support/tickets/{ticket_id}", headers=admin, json={"status": "closed"})
            check("ticket status update", patched.status_code == 200 and patched.json().get("status") == "closed", f"{patched.status_code} {patched.text[:200]}")

        # ---------- 2. MCP server ----------
        r = await c.get(f"{BASE}/mcp/")
        check("MCP without API key rejected", r.status_code in (401, 404), str(r.status_code))

        url = f"{BASE}/mcp/"
        headers = {"X-MCP-API-Key": MCP_KEY}

        async def list_tools(session):
            result = await session.list_tools()
            return [t.name for t in result.tools]

        names = await mcp_call(url, headers, list_tools)
        check("MCP tools exposed", {"list_languages", "list_voices", "synthesize_speech", "search_knowledge", "create_support_ticket", "chat"} <= set(names), f"tools={names}")

        async def call_lang(session):
            return await session.call_tool("list_languages", {})

        langs = await mcp_call(url, headers, call_lang)
        check("MCP list_languages call works", "55" in str(langs.content)[:400] or "Bengali" in str(langs.content), str(langs.content)[:100])

        async def call_kb(session):
            return await session.call_tool("search_knowledge", {"business_slug": slug, "query": "refund 30 days"})

        kb = await mcp_call(url, headers, call_kb)
        check("MCP knowledge search works", "refund" in str(kb.content).lower(), str(kb.content)[:120])

        # ---------- 3. outbound MCP tools in the agent ----------
        from app.agent.mcp_tools import get_mcp_tools
        from app.config import settings

        settings.mcp_servers_json = json.dumps([{"url": url, "headers": headers}])
        tools = await get_mcp_tools()
        check("agent discovers outbound MCP tools", len(tools) >= 6, f"count={len(tools)}")
        if tools:
            out = await tools[0].ainvoke({})
            check("agent can invoke an MCP tool", bool(str(out).strip()), str(out)[:80])

        # ---------- 4. voice training + self-improvement ----------

        r = await c.post(f"{BASE}/auth/register", json={"email": f"vtrain-{int(time.time())}@example.com", "password": "supersecret1"})
        tok, auth = r.json()["access_token"], {"Authorization": f"Bearer {r.json()['access_token']}"}
        phrase = (await c.get(f"{BASE}/voices/consent-phrase", params={"lang": "en"})).json()["phrase"]
        sample = wav_bytes()
        clone = await c.post(f"{BASE}/voices/clone", headers=auth, data={
            "name": "Trained voice", "consent": "true", "consent_lang": "en",
            "consent_phrase_text": phrase, "sample_lang": "en",
        }, files={"sample": ("s.wav", sample, "audio/wav"), "consent_audio": ("c.wav", sample, "audio/wav")})
        check("clone submitted with consent", clone.status_code == 201, str(clone.status_code))
        voice_id = clone.json()["voice"]["id"]
        # approve via admin so nightly job sees a ready cloned voice
        approved = await c.post(f"{BASE}/admin/voices/{voice_id}/moderate", headers=admin, json={"decision": "approve"})
        check("clone approved by admin", approved.status_code == 200, str(approved.status_code))

        trained = await c.post(f"{BASE}/voices/{voice_id}/train", headers=auth)
        check("voice training job produces profile", trained.status_code == 200 and trained.json()["status"] == "ready", f"features={str(trained.json().get('features'))[:140]}")
        status = await c.get(f"{BASE}/voices/{voice_id}/training", headers=auth)
        check("training status persisted", status.json()["profile_version"] == 1 and status.json()["adapted"], str(status.json()["profile_version"]))

        # nightly self-improvement (inline path with empty ctx)
        from app.workers.tasks import nightly_voice_improvement

        night = await nightly_voice_improvement({})
        check("nightly self-improvement schedules training", night["scheduled"] >= 1, str(night))
        status2 = await c.get(f"{BASE}/voices/{voice_id}/training", headers=auth)
        check("daily retraining bumps profile version", status2.json()["profile_version"] >= 2, f"version={status2.json()['profile_version']}")

        # adapted synthesis actually runs through the profile
        conv = (await c.post(f"{BASE}/conversations", headers=auth, json={"title": "voice train"})).json()
        import websockets

        uri = f"ws://localhost:8000/ws/chat/{conv['id']}?token={tok}"
        async with websockets.connect(uri, max_size=8 * 1024 * 1024) as ws:
            while True:
                fr = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if fr["type"] == "ready":
                    break
            await ws.send(json.dumps({"type": "speak", "text": "Hello from an adapted voice.", "lang": "en", "voice_id": voice_id}))
            while True:
                fr = json.loads(await asyncio.wait_for(ws.recv(), 120))
                if fr["type"] in ("done", "error"):
                    break
        check("synthesis with trained voice profile", fr["type"] == "done" and bool(fr.get("audio_id")), f"engine={fr.get('engine')} fallback={fr.get('fallback')}")

    print("\n==== SUMMARY ====")
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL':<5} {name} {detail}")
    if any(not ok for _, ok, _ in results):
        raise SystemExit(1)
    print("\nV2 EXPANSION: ALL PASS")


asyncio.run(main())
