Bohurupi — Pure-Python Multilingual Voice Agent
PRD · SRS · UI/UX · Architecture · Build Plan — v1.0
Name: Bohurupi (বহুরূপী — "one who takes many forms"). The agent answers in any language and speaks in any voice: a preset, a custom-tuned voice, or a consented clone.
One-line pitch: Ask or speak in any language, get the answer spoken back in the language and voice you choose, from a responsive web app built entirely in Python.
1. Product Requirements (PRD)
1.1 Problem
Voice assistants lock users into a few languages and fixed voices. Creators, educators, support teams and accessibility users need answers spoken in many languages and in a voice that fits the audience, without stitching together five tools.
1.2 Goals
1.  Any input language (text or speech) → agent reasoning → reply in any target language.
2.  Reply spoken in a selectable voice: preset, style-adjusted, or cloned from a short consented sample.
3.  Voice can be changed per response, mid-conversation, without losing context.
4.  Fully responsive UI (phone, tablet, desktop) written in Python only.
5.  Works online with cloud engines, and offline/self-hosted with open models.
1.3 Non-goals (v1)
Real-time phone telephony, video lip-sync, music/singing synthesis, impersonating people without consent.
1.4 Personas
Persona
Need
Creator (Rafi)
Narrate scripts in Bangla, English, Hindi, Arabic with one consistent brand voice
Teacher (Nusrat)
Explain a topic, then hear it in the student's mother tongue
Support lead (Imran)
Agent replies in the caller's language with a calm, friendly voice
Accessibility user
Everything read aloud, adjustable speed and voice
1.5 Core features
ID
Feature
Priority
F1
Chat agent (text in, text + audio out)
P0
F2
Speech input (mic or file upload) with auto language detection
P0
F3
Output language selector (auto / fixed / per message)
P0
F4
Voice library: presets by language, gender, style
P0
F5
Voice switcher on every reply ("re-speak in another voice/language")
P0
F6
Voice cloning from 10–30 s sample with consent gate
P1
F7
Voice-to-voice mode: speak, hear the reply in another voice
P1
F8
Style controls: speed, pitch, emotion, pauses, effects
P1
F9
Engine fallback chain (quality → coverage)
P0
F10
Export reply as MP3/WAV, share link
P1
F11
Agent tools: web search, translate, summarize, read document aloud
P1
F12
Conversation history, saved voices, usage dashboard
P1
F13
Audio watermark + consent log for cloned voices
P0
1.6 Success metrics
• Time to first audio (streamed) under 2.5 s for short replies on GPU, under 5 s on CPU.
• 95% of replies in the 20 launch languages play without fallback errors.
• Voice switch (re-speak) under 3 s using cached translation.
• Mobile Lighthouse score above 85; UI usable at 360 px width.
1.7 Release plan
• R1 (MVP): F1–F5, F9, F13. Text chat, 3 engines, 20 languages.
• R2: F2, F7, F8, F10, voice library growth.
• R3: F6, F11, F12, offline bundle.
2. Software Requirements (SRS)
2.1 Functional requirements
ID
Requirement
FR-1
The system shall accept text or audio input and detect its language automatically.
FR-2
The agent shall produce a text reply in the user-chosen output language, translating when needed.
FR-3
The system shall synthesize the reply with the selected voice and stream audio as it is generated.
FR-4
The user shall be able to re-speak any past reply with a different voice or language without re-running the LLM.
FR-5
If the chosen engine lacks the language, the system shall fall back to the next engine and tell the user which voice was used.
FR-6
Cloning shall require an explicit consent checkbox, a spoken consent phrase match, and shall be logged.
FR-7
Every synthetic audio file shall carry an inaudible watermark and metadata tag.
FR-8
The system shall store conversations, voices and settings per user.
FR-9
Admins shall be able to enable/disable engines, languages and voices.
FR-10
The UI shall adapt layout at 360, 768 and 1200 px breakpoints.
2.2 Non-functional requirements
Area
Target
Performance
Streaming TTS in chunks of one sentence; p95 re-speak latency under 3 s
Scalability
Stateless API workers; TTS jobs on a queue; scale workers independently
Reliability
Engine health checks, circuit breaker, automatic fallback
Security
JWT auth, rate limits, upload validation, per-user storage isolation, secrets in env
Privacy
Voice samples encrypted at rest; delete-my-voice removes samples and embeddings
Accessibility
WCAG 2.1 AA, keyboard control, captions for every audio
Portability
Docker Compose; CPU mode and CUDA mode
2.3 System architecture
Browser (NiceGUI, responsive)
   │  WebSocket + HTTP
FastAPI app ── Auth / Rate limit
   │
Agent Orchestrator (LangGraph state machine)
   ├─ STT node        (faster-whisper + Silero VAD)
   ├─ Language node   (lingua-py detect)
   ├─ Reason node     (Claude API; tools)
   ├─ Translate node  (Claude, or Argos offline)
   ├─ Text-prep node  (normalize numbers, split sentences, SSML-like tags)
   ├─ Voice node      (Engine Registry → TTS / voice conversion)
   └─ Post node       (pedalboard effects, watermark, encode)
   │
Redis (cache, pub/sub, queue)  ·  Postgres/SQLite  ·  Object store (local/S3)
Worker pool (ARQ) → GPU/CPU TTS engines
2.4 Pipeline modes
1.  Text → Voice: text → agent → translate → TTS → audio.
2.  Voice → Voice: speech → STT → agent → translate → TTS in chosen voice.
3.  Re-speak: stored reply text → (optional translate, cached) → TTS with new voice.
4.  Read-aloud: pasted/uploaded document → chunk → translate → TTS.
2.5 Python library stack (all Python)
Layer
Library
Why
UI
NiceGUI (Quasar under the hood)
Pure-Python, responsive grid, dark mode, WebSocket native
API
FastAPI + Uvicorn
Async, typed, shares process with NiceGUI
Agent
LangGraph + anthropic SDK
Explicit state graph, tool calling, retries
STT
faster-whisper
~99 languages, fast on CPU/GPU
VAD
silero-vad
Trim silence, detect speech end
Language ID
lingua-language-detector
Accurate on short text
Translation
Claude (default), argostranslate (offline)
Quality online, privacy offline
TTS (quality)
Coqui XTTS-v2 (maintained fork coqui-tts)
Multilingual, cloning from short sample
TTS (light/fast)
Kokoro, Piper
Small, CPU-friendly, many voices
TTS (coverage)
edge-tts, transformers MMS-TTS
Wide language coverage incl. Bangla
Voice conversion
OpenVoice v2 or Seed-VC
Swap timbre onto any TTS output
Audio FX
pedalboard (Spotify), librosa, pydub
Pitch, EQ, reverb, loudness, encode
Watermark
audioseal
Detectable inaudible mark on generated audio
Jobs/cache
arq + redis-py
Async queue, cache of translations and audio
DB
SQLModel + Alembic
Typed models, migrations
Auth
authlib / PyJWT, passlib
Login and tokens
Validation
pydantic v2
Settings and schemas
Observability
structlog, prometheus-client
Logs and metrics
Testing
pytest, pytest-asyncio, jiwer
Unit tests and STT word-error-rate checks
Licensing note: check each model's license before commercial use (XTTS-v2 uses the Coqui Public Model License; edge-tts relies on an unofficial Microsoft endpoint, so treat it as a convenience fallback, not a core dependency).
2.6 Engine Registry (the heart of "any language, any voice")
Every engine implements one interface, so adding a new one is a single file.
# app/engines/base.py
from typing import Protocol, AsyncIterator
from pydantic import BaseModel

class VoiceInfo(BaseModel):
    id: str
    name: str
    languages: list[str]      # BCP-47 codes
    gender: str | None = None
    styles: list[str] = []
    clonable: bool = False

class TTSEngine(Protocol):
    name: str
    def supports(self, lang: str) -> bool: ...
    def list_voices(self) -> list[VoiceInfo]: ...
    async def synthesize(self, text: str, lang: str, voice_id: str,
                         speed: float = 1.0, style: str | None = None
                         ) -> AsyncIterator[bytes]: ...   # PCM chunks
# app/engines/registry.py
class Registry:
    def __init__(self, engines): self.engines = engines
    def pick(self, lang, voice_id):
        for e in self.engines:                      # ordered by quality
            if e.supports(lang) and e.healthy():
                return e
        raise NoEngineForLanguage(lang)
Fallback order example: XTTS-v2 → Kokoro/Piper → MMS-TTS → edge-tts. If the chosen voice cannot speak the target language, run the TTS in a native voice and then apply voice conversion to match the chosen timbre.
2.7 Data model
Table
Key fields
users
id, email, password_hash, role, created_at
conversations
id, user_id, title, default_lang, default_voice_id
messages
id, conversation_id, role, text, lang, translations (JSON), created_at
audio_assets
id, message_id, voice_id, lang, engine, path, duration, watermark_id
voices
id, owner_id (null = preset), name, engine, languages, style_json, sample_path, embedding_path
consents
id, voice_id, user_id, phrase_audio_path, accepted_at, ip
settings
user_id, theme, speed, auto_play, captions
usage_events
id, user_id, type, chars, seconds, created_at
2.8 API (REST + WebSocket)
Method
Path
Purpose
POST
/auth/login
Token
POST
/chat
Send text; returns message id, streams text
WS
/ws/chat/{conv_id}
Stream text tokens + audio chunks
POST
/stt
Upload audio, get transcript + language
POST
/messages/{id}/respeak
Body: {voice_id, lang, speed, style}
GET
/voices
Filter by lang, gender, style
POST
/voices/clone
Sample + consent → new voice
DELETE
/voices/{id}
Remove voice and sample
GET
/audio/{id}
Stream/download audio
GET
/health/engines
Engine status
2.9 Streaming design
Split the reply into sentences. Send each sentence to the TTS worker as soon as the LLM finishes it, push PCM chunks over the WebSocket, and play with the Web Audio API (queue of chunks). First sound starts after the first sentence, not the whole reply.
2.10 Error handling
Failure
Behavior
Engine down or slow
Circuit breaker opens, next engine used, UI shows "Spoken with fallback voice"
Language unsupported by all engines
Show text reply and a notice; offer nearest language
STT low confidence
Show transcript for edit before sending
Clone sample too noisy
Reject with guidance (length, quiet room)
LLM error
Retry with backoff, then show a clear message
2.11 Security and responsible use
• Cloning only with consent; the sample owner can delete it any time.
• Block cloning of public figures via a simple name/voice-print check on sample metadata and a terms gate.
• Watermark every output; provide a /detect endpoint.
• Rate limit TTS minutes per user; validate file type, size (max 20 MB) and duration.
• Never log raw voice samples; encrypt at rest.
3. UI/UX Design
3.1 Design principles
Calm, off-white, one primary action per screen, large touch targets, voice always one tap away.
3.2 Design tokens
Token
Value
Background
#FAFAF8 (dark: #111214)
Surface
#FFFFFF (dark: #1A1C1F)
Border
#E7E5E0
Text
#1B1B1B / muted #6B6B66
Primary
#5B4BFF (violet)
Accent (playing)
#00B386
Danger
#D93B3B
Font
Inter; Noto Sans Bengali / Arabic / Devanagari / CJK fallbacks
Radius
14 px cards, 999 px pills
Spacing scale
4, 8, 12, 16, 24, 32
Language fonts matter: load Noto families so every script renders correctly, and support RTL (Arabic, Urdu, Hebrew) with dir="rtl" per message bubble.
3.3 Responsive layout
Breakpoint
Layout
360–767 px (phone)
Single column. Bottom tab bar: Chat · Voices · History · Settings. Mic button docked above the composer. Voice picker as a bottom sheet.
768–1199 px (tablet)
Collapsible left rail (icons), chat centered, voice picker as side drawer.
1200 px+ (desktop)
Three panes: conversations (left), chat (center), voice and style panel (right).
NiceGUI implementation: use ui.splitter/ui.row with Quasar classes (col-12 col-md-8, gt-sm, lt-md) and ui.dark_mode().
3.4 Screens
1.  Chat (home)
    ◦ Header: conversation title, language chip ("Reply in: বাংলা"), voice chip ("Voice: Ayra").
    ◦ Message bubbles with text, translation toggle, and an audio bar (play, waveform, speed, download).
    ◦ Per-message "Change voice" pill → opens voice sheet → re-speak.
    ◦ Composer: text field, mic (hold to talk / tap to toggle), send, attach.
2.  Voice library
    ◦ Search + filters (language, gender, style).
    ◦ Voice cards: name, languages, sample play button, "Use" and "Favorite".
    ◦ Sections: Presets, My voices, Cloned.
3.  Clone a voice (wizard)
    ◦ Step 1 Consent (checkbox + read-aloud phrase) → Step 2 Record or upload 10–30 s → Step 3 Quality check → Step 4 Name and test sentence → Save.
4.  Voice Studio
    ◦ Sliders: speed, pitch, warmth, pause length; emotion dropdown; effect presets (Clean, Radio, Hall). Live preview sentence in the user's language.
5.  History
    ◦ Searchable conversations, export audio, delete.
6.  Settings
    ◦ Theme, default language, default voice, auto-play, captions, engine preference (Quality / Fast / Offline), data and privacy (delete voices).
7.  Admin (role-gated)
    ◦ Engine health, language toggles, voice moderation, usage charts.
3.5 Key interaction flows
Speak a question, hear it in another voice Tap mic → speak (VAD stops on silence) → transcript appears → agent replies → text streams → first sentence plays in selected voice → tap "Change voice" → pick new voice → re-speak from cache.
Clone a voice Voices → Clone → consent → record → quality check pass → name → test → voice appears under My voices → set as default.
3.6 Components
MessageBubble, AudioBar (waveform via canvas), VoiceCard, LanguagePicker (searchable, flags avoided in favor of language names), VoiceSheet, MicButton (states: idle, listening, processing), StyleSliders, EngineBadge, ConsentGate, EmptyState, Toast.
3.7 States and microcopy
• Listening: pulsing ring, "Listening… tap to stop".
• Generating voice: shimmering waveform, "Preparing voice…".
• Fallback used: small badge "Spoken with Kokoro (fallback)".
• Error: plain sentence plus a retry button, never a stack trace.
• Empty chat: three starter prompts in the user's default language.
3.8 Accessibility
Full keyboard control (Space play/pause, M mic), ARIA labels on audio controls, captions always available, reduced-motion respected, contrast 4.5:1 minimum.
4. Project Structure
bohurupi/
├─ app/
│  ├─ main.py              # FastAPI + NiceGUI mount
│  ├─ config.py            # pydantic-settings
│  ├─ agent/
│  │  ├─ graph.py          # LangGraph nodes and edges
│  │  ├─ tools.py          # search, translate, summarize
│  │  └─ prompts.py
│  ├─ audio/
│  │  ├─ stt.py            # faster-whisper + VAD
│  │  ├─ textprep.py       # sentence split, number/date normalization
│  │  ├─ fx.py             # pedalboard chain
│  │  └─ watermark.py      # audioseal
│  ├─ engines/
│  │  ├─ base.py  registry.py
│  │  ├─ xtts.py  kokoro.py  piper.py  mms.py  edge.py
│  │  └─ convert.py        # OpenVoice / Seed-VC
│  ├─ api/                 # routers: auth, chat, voices, audio, admin
│  ├─ db/                  # models.py, session.py, migrations/
│  ├─ workers/             # arq tasks
│  └─ ui/                  # NiceGUI pages and components
├─ tests/
├─ docker/ (Dockerfile.cpu, Dockerfile.gpu, compose.yml)
├─ .env.example
└─ pyproject.toml
4.1 Agent graph skeleton
from langgraph.graph import StateGraph, END

class S(TypedDict):
    text: str; in_lang: str; out_lang: str
    reply: str; voice_id: str; audio_path: str

g = StateGraph(S)
g.add_node("detect", detect_language)
g.add_node("reason", call_claude)
g.add_node("translate", translate_if_needed)
g.add_node("speak", synthesize_stream)
g.set_entry_point("detect")
g.add_edge("detect", "reason")
g.add_edge("reason", "translate")
g.add_edge("translate", "speak")
g.add_edge("speak", END)
agent = g.compile()
5. Build Plan
Phase
Weeks
Deliverables
0
1
Repo, config, Docker, CI, DB models, auth
1
2–3
Agent graph, Claude integration, Engine Registry with Kokoro + edge-tts, text → audio, NiceGUI chat page
2
4
Streaming audio over WebSocket, language/voice pickers, re-speak with cache
3
5
STT + VAD, mic UI, voice-to-voice mode
4
6
XTTS-v2, MMS-TTS, fallback chain, health checks
5
7
Voice Studio (pedalboard), export, history
6
8
Cloning wizard, consent log, watermark, /detect
7
9
Admin, metrics, rate limits, hardening
8
10
Offline bundle (Argos + local models), docs, launch
6. Testing Strategy
• Unit: text normalization, registry fallback, consent rules.
• Audio quality: round-trip test (TTS → faster-whisper → jiwer word-error-rate under a threshold per language).
• Load: 50 concurrent streams; confirm queue and autoscaling.
• UI: Playwright at 360, 768, 1280 px; RTL and Bangla/Arabic rendering snapshots.
• Security: upload fuzzing, auth bypass, rate-limit tests.
7. Deployment
• Docker Compose: web, worker (GPU optional), redis, postgres.
• Env: ANTHROPIC_API_KEY, DATABASE_URL, REDIS_URL, STORAGE_PATH, ENGINE_ORDER, JWT_SECRET.
• Reverse proxy with HTTPS (needed for microphone access), WebSocket upgrade enabled.
• Model weights downloaded on first boot into a mounted volume; health endpoint reports ready only after warm-up.
8. Risks and Mitigations
Risk
Mitigation
Poor quality in low-resource languages
Engine fallback, per-language quality scorecard, show badge
Voice misuse
Consent gate, watermark, rate limits, moderation, terms
High GPU cost
Cache audio and translations, CPU engines for short replies, queue batching
Model licenses
License register in repo, per-engine enable flag
Latency on long replies
Sentence streaming, prefetch next sentence
9. Open Decisions
1.  Cloud-only first, or ship the offline bundle in R1?
2.  Which 20 launch languages (suggested: Bangla, English, Hindi, Urdu, Arabic, Spanish, French, German, Portuguese, Russian, Turkish, Chinese, Japanese, Korean, Italian, Dutch, Polish, Indonesian, Tamil, Vietnamese)?
3.  Public SaaS or self-hosted tool? This changes billing, moderation and cloning policy.