"""Speech-to-text via faster-whisper with built-in Silero VAD.

Heavy imports are lazy so the API boots without the `audio` extra installed;
/stt then reports a clear 503 instead of crashing.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger("bohurupi.stt")

_model = None
_model_size: str | None = None


@dataclass
class Transcript:
    text: str
    language: str  # ISO 639-1
    confidence: float  # 0..1 (avg exp(logprob))


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        import numpy  # noqa: F401
        import soundfile  # noqa: F401

        return True
    except ImportError:
        return False


def _get_model():
    global _model, _model_size
    from app.config import settings

    if _model is not None and _model_size == settings.whisper_model_size:
        return _model
    from faster_whisper import WhisperModel

    logger.info("Loading faster-whisper '%s' (cpu, int8) ...", settings.whisper_model_size)
    _model = WhisperModel(
        settings.whisper_model_size, device="cpu", compute_type="int8"
    )
    _model_size = settings.whisper_model_size
    return _model


def transcribe(wav_bytes: bytes, language: str | None = None) -> Transcript:
    """Transcribe audio bytes (wav/mp3/webm). Blocking; call via asyncio.to_thread."""
    import io

    import numpy as np
    import soundfile as sf

    model = _get_model()
    x, _sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=True)
    mono = x.mean(axis=1)

    segments, info = model.transcribe(
        mono,
        language=language or None,
        vad_filter=True,  # Silero VAD built in
        beam_size=1,
        condition_on_previous_text=False,
    )
    parts, logprobs = [], []
    for seg in segments:
        parts.append(seg.text.strip())
        logprobs.append(seg.avg_logprob)
    text = " ".join(p for p in parts if p)
    confidence = float(np.exp(np.mean(logprobs))) if logprobs else 0.0
    return Transcript(text=text, language=info.language, confidence=confidence)
