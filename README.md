# Bohurupi — বহুরূপী

**Ask or speak in any language. Get the answer spoken back in the language and voice you choose.**

Bohurupi is a multilingual voice agent: type or talk in any language, the agent reasons with
Z.AI GLM, replies in your chosen output language, and speaks the answer in any voice from a
preset library — or a cloned voice gated by explicit consent. Every generated audio carries an
identifiable watermark.

| Piece    | Tech                                                                 |
| -------- | -------------------------------------------------------------------- |
| Frontend | Next.js 16 (App Router, React 19), Tailwind CSS v4, shadcn/ui, Inter + Noto script fonts |
| Backend  | Python 3.12, FastAPI, LangGraph, SQLModel + Alembic, Redis + ARQ      |
| Speech   | Kokoro-82M (ONNX, CPU) + edge-tts (coverage), faster-whisper (STT)    |
| LLM      | Z.AI GLM (`glm-4.6`) via OpenAI-compatible endpoint — provider-pluggable |
| Infra    | Docker Compose: web / api / worker / postgres / redis                 |

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env: set ZAI_API_KEY and JWT_SECRET
docker compose up --build
# web  -> http://localhost:3000
# api  -> http://localhost:8000  (docs at /docs in dev)
```

## Quick start (dev, no Docker)

**API** (needs Python 3.12 via [uv](https://docs.astral.sh/uv/)):

```bash
cd api
uv sync --extra audio          # core + speech stack
cp .env.example .env           # set ZAI_API_KEY
uv run uvicorn app.main:app --port 8000 --reload
```

**Web** (needs Node 20+):

```bash
cd web
npm install
npm run dev                    # http://localhost:3000
```

The first request to a Kokoro voice auto-downloads the model (~330 MB) into
`api/storage/models/`. `edge-tts` voices cover all 55 languages immediately.

## Features (PRD v1.0 mapping)

- **F1 Chat agent** — text in, streamed text + audio out (`/ws/chat/{conv_id}`)
- **F2 Speech input** — mic recording → faster-whisper STT with auto language ID
- **F3 Output language** — auto / fixed / per message, 55 languages, RTL aware
- **F4 Voice library** — presets by language/gender/style + my voices
- **F5 Voice switcher** — “Change voice” on any reply; re-speak uses cached translation (no LLM)
- **F6 Voice cloning** — 10–30 s sample with consent phrase (typed + recorded), moderation, encrypted storage
- **F7 Voice-to-voice** — toggle in chat; speak, hear the reply
- **F8 Style controls** — Voice Studio: speed, pitch, emotion, Clean/Radio/Hall effects
- **F9 Engine fallback** — quality-ordered registry with circuit breaker; UI shows which voice spoke
- **F10 Export** — every reply downloadable as WAV
- **F13 Watermark + consent log** — audioseal when the `fx` extra is installed, metadata mark always; consent rows with IP

## Architecture

```
Browser (Next.js + shadcn/ui)
   │  REST + WebSocket (text tokens + PCM audio frames)
FastAPI ── auth / rate limits / quotas
   │
LangGraph: detect → reason (GLM + tools) → translate
   │  sentence scheduler (first audio < first reply)
Engine Registry: Kokoro → edge-tts (circuit breaker, health, fallback)
   │
Postgres/SQLite · Redis (cache, quotas) · ARQ worker · storage/audio + samples (encrypted)
```

## Repository layout

```
web/    Next.js app — src/app routes, src/components/chat, src/lib (api, ws, audio engine)
api/    FastAPI — app/agent (LangGraph), app/engines (registry), app/audio (stt, fx, watermark),
        app/api (routers), app/db (SQLModel + db/migrations), app/workers (ARQ)
docker-compose.yml   full stack
.env.example         all configuration
```

## Routes

- `/` — public landing page (pill nav, hero, demo card, features, CTA, footer)
- `/login`, `/register`, `/forgot-password`, `/reset-password` — separate auth screens
- `/chat`, `/support`, `/voices`, `/voices/clone`, `/studio`, `/history`, `/settings`, `/admin` — app (auth required)

In dev/staging, `/auth/demo-accounts` + `/auth/demo-login` seed a one-click demo account
(`DEMO_EMAIL` / `DEMO_PASSWORD`); both return 404 in prod. Password reset sends via SMTP when
configured; without SMTP the local dev flow surfaces a reset link on screen (prod fails honestly).

## Customer support agent, MCP and voice training (v2)

- `/support` — knowledge-grounded support chat for any configured business, in any language,
  with LLM-driven human escalation that creates a real `SupportTicket`.
- Admin → Businesses / Tickets — create a tenant, index documents (chunked + hashed TF-IDF
  retrieval), manage escalations.
- `POST /voices/{id}/train` — learns a voice-adaptation profile from consented samples;
  a nightly ARQ cron job retrains every approved cloned voice (`profile_version` increases).
  The adapter applies measured pitch/speed characteristics to synthesis; it is **voice
  adaptation, not neural timbre cloning**, and the API reports the engine actually used.
- MCP server at `/mcp` (Streamable HTTP, `X-MCP-API-Key` required when `MCP_API_KEY` is set)
  exposes languages, voices, TTS, knowledge search, tickets and chat as real tools.
- Web search via free libraries (Wikipedia REST + DuckDuckGo, BeautifulSoup) is bound
  into the agent automatically: `web_search`, `fetch_url`, `wikipedia_search` — no API key.
- STT applies local MIT-licensed `noisereduce` spectral gating + high-pass filtering before
  Whisper (`STT_DENOISE*`) so voices are heard in noisy/crowded rooms. If suppression leaves
  no speech, recognition automatically retries the original audio.
- `MCP_SERVERS_JSON` connects external MCP servers; their tools are exposed to the
  LangGraph agent at runtime (`app/agent/mcp_tools.py`).

## Testing

```bash
cd api && uv run pytest          # 74 tests: auth, db, security, fixes, textprep, registry, consent, API
cd web && npm run build          # typed + production build
```

Audit scripts against a running API on :8000:

- `uv run python scripts/audit_api.py` — live audit: auth, RBAC, IDOR, quotas, CRUD, WS (PASS/FAIL evidence)
- `uv run python scripts/audit_quota.py` — quota proof (start the API with `QUOTA_FREE_CHARS=100`)
- `uv run python scripts/audit_chat_stream.py` — full chat-pipeline E2E with a local mock LLM (no real key needed)
- `uv run python scripts/audit_ai_real.py` — full AI E2E against the real configured provider (chat, translation, re-speak, STT, voice-to-voice)
- `uv run python scripts/audit_ai_nonllm.py` — real TTS/STT/consent verification without LLM calls
- `uv run python scripts/audit_languages.py` — verifies all 55 languages, seeded voices, new-language TTS/translation/detection
- `uv run python scripts/audit_v2.py` — support agent + RAG + tickets, MCP server/client, voice training and nightly self-improvement

Web E2E: `cd web && npx playwright test` (expects web on :3300 + API on :8000; 22 scenarios).
For stable runs use the production web build: `npm run build && npm run start -- --port 3300`.

Engine smoke test: `uv run python scripts/test_tts.py` (writes WAVs to `api/storage/`).
End-to-end: `uv run python scripts/test_e2e.py` against a running API (no LLM key needed).

## Security notes

- JWT auth, per-user data isolation, rate limits + daily TTS quotas per plan
- Voice samples & consent audio encrypted at rest (Fernet, AES-CBC + HMAC)
- Admins enable/disable engines; cloned voices pass moderation before use
- Cloning requires the checkbox + exact phrase match + recorded consent + name/figure policy gate
- `GET /audio/{id}/detect` (admin) checks a file for the watermark

## License notes

- Kokoro-82M: Apache-2.0. faster-whisper: MIT. edge-tts uses an unofficial Microsoft
  endpoint — treat it as a convenience/coverage fallback, not the core dependency.
- Check each added engine's license before commercial use (see PRD §2.5).
