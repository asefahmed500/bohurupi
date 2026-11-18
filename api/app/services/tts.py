"""TTS synthesis service: registry + FX + watermark + persistence.

All audio is normalized to mono 16-bit PCM (see engines.base.AudioChunk).
"""

import base64
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlmodel import Session

from app.audio import fx, watermark
from app.config import settings
from app.db.models import AudioAsset, UsageEvent
from app.engines.base import AudioChunk, EngineUnavailable, NoEngineForLanguage
from app.engines.registry import get_registry
from app.services import storage

logger = logging.getLogger("bohurupi.tts")


@dataclass
class SynthMeta:
    """Filled in by synthesize_pcm while it streams."""

    engine: str = ""
    voice_id: str = ""
    native_voice_id: str = ""
    fallback_used: bool = False
    sample_rate: int = 0
    duration: float = 0.0
    watermark_id: str | None = None


async def synthesize_pcm(
    text: str,
    lang: str,
    voice_id: str,
    meta: SynthMeta,
    speed: float = 1.0,
    style: str | None = None,
    effect: str | None = None,
    pitch_semitones: float = 0.0,
) -> AsyncIterator[AudioChunk]:
    """Yield processed PCM chunks, transparently walking the engine fallback
    chain (FR-5). Fills `meta` with what actually spoke.

    Raises NoEngineForLanguage when no engine can speak `lang`.
    """
    registry = get_registry()
    picked = registry.pick(lang, voice_id)

    for _attempt in range(3):
        engine, voice = picked.engine, picked.voice
        try:
            produced = False
            last_chunk: AudioChunk | None = None
            async for chunk in engine.synthesize(
                text, lang, voice.id, speed=speed, style=style
            ):
                produced = True
                last_chunk = chunk
                pcm = chunk.pcm
                if pitch_semitones:
                    pcm = fx.pitch_shift(pcm, chunk.sample_rate, pitch_semitones)
                if effect and effect not in ("clean", None, ""):
                    pcm = fx.apply_effect(pcm, chunk.sample_rate, effect)
                yield AudioChunk(pcm=pcm, sample_rate=chunk.sample_rate)
            if not produced or last_chunk is None:
                raise EngineUnavailable("engine produced no audio")
            registry.record_success(engine.name)
            meta.engine = engine.name
            meta.voice_id = voice.id
            meta.native_voice_id = voice.native_voice_id
            meta.fallback_used = picked.fallback_used
            meta.sample_rate = last_chunk.sample_rate
            meta.duration = len(last_chunk.pcm) and 0.0  # duration set by caller
            return
        except NoEngineForLanguage:
            raise
        except Exception as e:  # engine failure mid-stream -> next engine
            registry.record_failure(engine.name)
            logger.warning("Engine '%s' failed (%s); trying fallback", engine.name, e)
            picked = registry.pick(lang, "")  # drop preference -> next quality engine

    raise EngineUnavailable("all engines failed")


async def synthesize_to_wav_file(
    session: Session,
    *,
    text: str,
    lang: str,
    voice_id: str,
    message_id: str | None,
    user_id: str,
    speed: float = 1.0,
    style: str | None = None,
    effect: str | None = None,
    pitch_semitones: float = 0.0,
) -> tuple[AudioAsset, SynthMeta]:
    """Full-text synthesis for REST paths (re-speak, export). Persists the WAV,
    an AudioAsset row and a usage event."""
    registry = get_registry()
    meta = SynthMeta()
    buf = bytearray()

    async for chunk in synthesize_pcm(
        text,
        lang,
        voice_id,
        meta,
        speed=speed,
        style=style,
        effect=effect,
        pitch_semitones=pitch_semitones,
    ):
        buf.extend(chunk.pcm)
        meta.sample_rate = chunk.sample_rate

    if not buf:
        raise EngineUnavailable("no audio produced")

    pcm = bytes(buf)
    meta.duration = storage.pcm_duration(pcm, meta.sample_rate)

    if settings.watermark_enabled:
        pcm, meta.watermark_id = watermark.watermark(pcm, meta.sample_rate)

    asset_id = uuid.uuid4().hex
    path = storage.audio_path(asset_id)
    storage.write_wav(pcm, meta.sample_rate, path)

    registry.find_voice(meta.voice_id or voice_id)  # validate the voice exists
    asset = AudioAsset(
        id=asset_id,
        message_id=message_id,
        voice_id=meta.voice_id or voice_id,
        lang=lang,
        engine=meta.engine,
        path=str(path.relative_to(storage.root())),
        duration=meta.duration,
        sample_rate=meta.sample_rate,
        watermark_id=meta.watermark_id,
    )
    session.add(asset)
    session.add(
        UsageEvent(user_id=user_id, type="tts", chars=len(text), seconds=meta.duration)
    )
    session.commit()
    session.refresh(asset)
    return asset, meta


# ---- WS frame helpers ----


def audio_frame(seq: int, chunk: AudioChunk) -> dict:
    return {
        "type": "audio",
        "seq": seq,
        "sr": chunk.sample_rate,
        "b64": base64.b64encode(chunk.pcm).decode(),
    }
