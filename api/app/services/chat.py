"""Chat orchestration: the streaming pipeline behind /ws/chat/{conv_id}.

Pipeline modes (PRD §2.4):
  1. chat      text -> agent graph (streams tokens) -> per-sentence TTS
  2. voice     same as chat after STT
  3. respeak   stored reply text -> cached translate -> TTS with new voice
  4. readaloud document -> chunk -> translate -> TTS

The LangGraph graph handles detect -> reason (+tools) -> translate. Sentence
scheduling and TTS streaming live here so first audio starts after the first
sentence, not the whole reply (PRD §2.9).
"""

import asyncio
import base64
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlmodel import Session, select

from app.agent.graph import get_graph
from app.agent.llm import llm_ready
from app.agent.prompts import SYSTEM_PROMPT
from app.audio import textprep
from app.config import settings
from app.db.models import Conversation, Message, UsageEvent
from app.i18n import LANGUAGES
from app.services import cache as cache_svc
from app.services import storage
from app.services.cache import translation_cache_key
from app.services.tts import SynthMeta, audio_frame, synthesize_pcm

logger = logging.getLogger("bohurupi.chat")

HISTORY_MESSAGES = 12


def _now() -> datetime:
    return datetime.now(UTC)


def _out_lang_instruction(out_lang: str) -> str:
    if out_lang and out_lang != "auto":
        lang = LANGUAGES.get(out_lang)
        if lang:
            return (
                f"Always write your reply in {lang.name} ({lang.native}). "
                f"Never use any other language."
            )
    return "Reply in the same language the user used."


def _resolve_reply_lang(final_state: dict, out_lang: str, in_lang: str) -> str:
    explicit = final_state.get("reply_lang")
    if explicit:
        return explicit
    if out_lang and out_lang != "auto":
        return out_lang
    return in_lang or "en"


def _build_messages(
    session: Session,
    conversation: Conversation,
    text: str,
    out_lang: str,
    exclude_message_id: str | None = None,
) -> list:
    prompt = SYSTEM_PROMPT.format(out_lang_instruction=_out_lang_instruction(out_lang))
    messages: list = [SystemMessage(content=prompt)]
    history = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())  # type: ignore[union-attr]
        .limit(HISTORY_MESSAGES + 1)
    ).all()
    for m in reversed(history):
        if exclude_message_id and m.id == exclude_message_id:
            continue  # the live user turn is appended below — never send it twice
        content = m.text
        if m.role == "assistant" and m.translations:
            key = out_lang if out_lang != "auto" else m.lang
            content = m.translations.get(key, content)
        messages.append(
            HumanMessage(content=content) if m.role == "user" else AIMessage(content=content)
        )
    messages.append(HumanMessage(content=text))
    return messages


async def stream_chat(
    session: Session,
    conversation: Conversation,
    user_id: str,
    text: str,
    out_lang: str = "auto",
    voice_id: str = "",
    speed: float = 1.0,
    style: str | None = None,
    effect: str | None = None,
) -> AsyncIterator[dict]:
    """Yield WS frames: status, lang, text_token, sentence_start, audio,
    sentence_end, done, error."""
    t_start = time.monotonic()

    if not llm_ready():
        yield {"type": "error", "message": "The AI engine is not configured (missing ZAI_API_KEY)."}
        return

    # persist the user's message
    user_msg = Message(conversation_id=conversation.id, role="user", text=text)
    session.add(user_msg)
    session.commit()
    session.refresh(user_msg)

    sink: asyncio.Queue[dict | None] = asyncio.Queue()
    # full-reply audio accumulated across sentences (persisted on done; F10 export)
    rendered: list[tuple[bytes, int]] = []
    spoken_chars = 0

    async def producer() -> None:
        nonlocal spoken_chars
        sentence_q: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()
        seq = 0

        async def tts_worker() -> None:
            nonlocal seq, spoken_chars
            while True:
                item = await sentence_q.get()
                if item is None:
                    return
                sentence, s_lang = item
                try:
                    meta = SynthMeta()
                    first = True
                    async for chunk in synthesize_pcm(
                        sentence,
                        s_lang,
                        voice_id,
                        meta,
                        speed=speed,
                        style=style,
                        effect=effect,
                    ):
                        if first:
                            await sink.put(
                                {
                                    "type": "sentence_start",
                                    "text": sentence,
                                    "lang": s_lang,
                                    "engine": meta.engine,
                                    "voice_id": meta.voice_id,
                                    "fallback": meta.fallback_used,
                                }
                            )
                            first = False
                        seq += 1
                        await sink.put(audio_frame(seq, chunk))
                        rendered.append((chunk.pcm, chunk.sample_rate))
                    spoken_chars += len(sentence)
                    await sink.put(
                        {
                            "type": "sentence_end",
                            "engine": meta.engine,
                            "voice_id": meta.voice_id,
                            "fallback": meta.fallback_used,
                        }
                    )
                except Exception as e:
                    logger.warning("TTS failed for a sentence: %s", e)
                    await sink.put(
                        {
                            "type": "sentence_error",
                            "message": "Voice engine could not speak this sentence.",
                        }
                    )

        worker = asyncio.create_task(tts_worker())
        buffer = ""
        reply_full = ""
        in_lang = ""
        final_state: dict = {}

        try:
            await sink.put({"type": "status", "stage": "thinking"})
            state_in = {
                "messages": _build_messages(
                    session, conversation, text, out_lang, exclude_message_id=user_msg.id
                ),
                "text": text,
                "in_lang": "",
                "out_lang": out_lang,
                "reply": "",
                "reply_lang": "",
                "translations": {},
            }

            async for mode, payload in get_graph().astream(
                state_in, stream_mode=["messages", "values"]
            ):
                if mode == "values":
                    final_state = payload
                    continue
                token, meta = payload
                # only stream reasoning tokens — the translate node runs a second
                # LLM call whose tokens would otherwise duplicate the text and be
                # spoken twice
                if isinstance(meta, dict) and meta.get("langgraph_node") not in (None, "reason"):
                    continue
                content = getattr(token, "content", "")
                if not content or not isinstance(content, str):
                    continue
                reply_full += content
                if not in_lang and final_state.get("in_lang"):
                    in_lang = final_state["in_lang"]
                await sink.put({"type": "text_token", "v": content})

                # schedule completed sentences for TTS in the reply language
                reply_lang = _resolve_reply_lang(final_state, out_lang, in_lang)
                sentences = textprep.split_sentences(buffer + content)
                if len(sentences) > 1:
                    for s in sentences[:-1]:
                        await sentence_q.put((s, reply_lang))
                    buffer = sentences[-1]
                elif sentences:
                    buffer = sentences[0]
                else:
                    buffer = buffer + content

            if buffer.strip():
                reply_lang = _resolve_reply_lang(final_state, out_lang, in_lang)
                await sentence_q.put((buffer.strip(), reply_lang))
            await sentence_q.put(None)
            await worker
        except Exception as e:
            logger.exception("Chat pipeline failed")
            await sink.put({"type": "error", "message": _friendly_error(e)})
            await sentence_q.put(None)
        finally:
            try:
                await asyncio.wait_for(asyncio.shield(worker), timeout=120)
            except Exception:
                pass
            reply_lang = _resolve_reply_lang(final_state, out_lang, in_lang)
            reply_text = final_state.get("reply") or reply_full

            done_frame: dict = {
                "type": "done",
                "user_message_id": user_msg.id,
                "lang": reply_lang,
                "text": reply_text,
                "latency_ms": int((time.monotonic() - t_start) * 1000),
            }

            if reply_text.strip():
                ai_msg = Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    text=reply_text,
                    lang=reply_lang,
                    translations=final_state.get("translations") or None,
                )
                session.add(ai_msg)
                session.add(UsageEvent(user_id=user_id, type="llm", chars=len(text)))
                session.commit()
                session.refresh(ai_msg)

                conversation.updated_at = _now()
                session.add(conversation)
                session.commit()

                done_frame["message_id"] = ai_msg.id

                # persist the full reply audio so history/export keep working (F10)
                if rendered:
                    done_frame["audio_id"] = await asyncio.to_thread(
                        _persist_reply_audio, session, ai_msg.id, user_id, rendered, reply_lang
                    )
                if spoken_chars:
                    from app.services.cache import add_usage

                    add_usage(user_id, spoken_chars)
            else:
                # reasoning failed (e.g. LLM not configured): nothing to persist
                done_frame["message_id"] = ""

            await sink.put(done_frame)
            await sink.put(None)

    task = asyncio.create_task(producer())
    try:
        while True:
            frame = await sink.get()
            if frame is None:
                break
            yield frame
    finally:
        await task


def _friendly_error(e: Exception) -> str:
    name = type(e).__name__
    message = str(e).lower()
    # Provider-side account problems must not be disguised as a transient busy
    # signal (real 429 bodies can mean "insufficient balance").
    permanent_phrases = (
        "insufficient balance",
        "no resource package",
        "recharge",
        "quota exceeded",
    )
    if any(phrase in message for phrase in permanent_phrases):
        return "The AI provider account has insufficient balance. Please top up the Z.AI account."
    if "APIConnection" in name or "httpx" in name.lower():
        return "Could not reach the AI service. Check your connection and try again."
    if "Authentication" in name or "401" in str(e) or "invalid api key" in message:
        return "The AI service rejected the API key. Check ZAI_API_KEY."
    if "RateLimit" in name or "429" in str(e):
        return "The AI service is busy. Please try again in a moment."
    return "Something went wrong while thinking. Please try again."


def _persist_reply_audio(
    session: Session,
    message_id: str,
    user_id: str,
    rendered: list[tuple[bytes, int]],
    lang: str,
) -> str:
    """Write the streamed reply as one WAV asset linked to the assistant message.

    Returns the audio id ("" when nothing could be persisted)."""
    import uuid

    from app.db.models import AudioAsset

    if not rendered:
        return ""
    sample_rate = rendered[0][1]
    pcm = bytearray()
    for chunk, sr in rendered:
        if sr != sample_rate:
            logger.warning(
                "Mixed sample rates in one reply (%s vs %s); skipping chunk",
                sr,
                sample_rate,
            )
            continue
        pcm.extend(chunk)
    if not pcm:
        return ""

    watermark_id = None
    if settings.watermark_enabled:
        from app.audio import watermark as wm

        pcm, watermark_id = wm.watermark(bytes(pcm), sample_rate)

    asset_id = uuid.uuid4().hex
    path = storage.audio_path(asset_id)
    storage.write_wav(bytes(pcm), sample_rate, path)
    asset = AudioAsset(
        id=asset_id,
        message_id=message_id,
        user_id=user_id,
        voice_id="",
        lang=lang,
        engine="",
        path=str(path.relative_to(storage.root())),
        duration=storage.pcm_duration(bytes(pcm), sample_rate),
        sample_rate=sample_rate,
        watermark_id=watermark_id,
    )
    session.add(asset)
    session.commit()
    return asset_id


# ---------------------------------------------------------------------------
# Mode 3: re-speak (FR-4) — cached translation + new voice, no LLM run
# ---------------------------------------------------------------------------


async def stream_respeak(
    session: Session,
    message: Message,
    user_id: str,
    voice_id: str,
    lang: str = "",
    speed: float = 1.0,
    style: str | None = None,
    effect: str | None = None,
    pitch_semitones: float = 0.0,
) -> AsyncIterator[dict]:
    """Re-speak an existing assistant reply in another voice/language."""
    from app.services.tts import synthesize_to_wav_file

    target = lang or message.lang or "en"
    translations = message.translations or {}
    t_start = time.monotonic()

    yield {"type": "status", "stage": "respeak"}

    if target not in translations:
        ck = translation_cache_key(message.text, target)
        cached = cache_svc.cache().get(ck)
        if cached:
            translations[target] = cached
        elif target != message.lang:
            from app.agent.tools import translate_text

            translations[target] = await translate_text(message.text, target)
            cache_svc.cache().set(ck, translations[target], ttl=60 * 60 * 24)
        else:
            translations[target] = message.text

        message.translations = translations
        session.add(message)
        session.commit()

    spoken_text = translations[target]
    yield {"type": "text_token", "v": spoken_text}

    asset, meta = await synthesize_to_wav_file(
        session,
        text=spoken_text,
        lang=target,
        voice_id=voice_id,
        message_id=message.id,
        user_id=user_id,
        speed=speed,
        style=style,
        effect=effect,
        pitch_semitones=pitch_semitones,
    )

    # stream the rendered wav back as audio frames
    pcm, sr = storage.read_wav(storage.audio_path(asset.id))
    step = sr // 5 * 2
    seq = 0
    for i in range(0, len(pcm), step):
        seq += 1
        yield {
            "type": "audio",
            "seq": seq,
            "sr": sr,
            "b64": base64.b64encode(pcm[i : i + step]).decode(),
        }

    yield {
        "type": "done",
        "message_id": message.id,
        "audio_id": asset.id,
        "lang": target,
        "voice_id": meta.voice_id,
        "engine": meta.engine,
        "fallback": meta.fallback_used,
        "duration": asset.duration,
        "latency_ms": int((time.monotonic() - t_start) * 1000),
    }
