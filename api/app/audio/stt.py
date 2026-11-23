"""Speech-to-text via faster-whisper with built-in Silero VAD.

Heavy imports are lazy so the API boots without the `audio` extra installed;
/stt then reports a clear 503 instead of crashing. Before recognition, audio
passes through local noise suppression (noisereduce spectral gating) so the
system can hear a voice in a noisy or crowded room.
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
    denoised: bool = False


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


def transcribe(
    wav_bytes: bytes,
    language: str | None = None,
    denoise: bool | None = None,
) -> Transcript:
    """Transcribe audio bytes (wav/mp3/webm). Blocking; call via asyncio.to_thread.

    `denoise=None` uses the server default; True/False overrides per request.
    """
    import io

    import numpy as np
    import soundfile as sf

    from app.config import settings

    x, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=True)
    mono = x.mean(axis=1)

    apply_denoise = settings.stt_denoise if denoise is None else denoise
    denoised = False
    if apply_denoise:
        from app.audio.denoise import denoise_samples

        mono = denoise_samples(
            mono,
            sr,
            strength=settings.stt_denoise_strength,
            stationary=settings.stt_denoise_stationary,
        )
        denoised = True

    model = _get_model()

    def _recognize(signal: np.ndarray):
        return model.transcribe(
            signal,
            language=language or None,
            vad_filter=True,  # Silero VAD — second stage after spectral gating
            beam_size=1,
            condition_on_previous_text=False,
        )

    segments, info = _recognize(mono)
    parts, logprobs = [], []
    for seg in segments:
        parts.append(seg.text.strip())
        logprobs.append(seg.avg_logprob)
    text = " ".join(p for p in parts if p)

    if apply_denoise and not text.strip() and denoised:
        # Safety: if the gate removed the voice along with the noise, retry
        # recognition on the untouched signal rather than returning silence.
        logger.info("Denoising removed all speech — retrying STT on the original audio")
        segments, info = _recognize(x.mean(axis=1))
        parts, logprobs = [], []
        for seg in segments:
            parts.append(seg.text.strip())
            logprobs.append(seg.avg_logprob)
        text = " ".join(p for p in parts if p)
        denoised = False

    confidence = float(np.exp(np.mean(logprobs))) if logprobs else 0.0
    return Transcript(
        text=text, language=info.language, confidence=confidence, denoised=denoised
    )
