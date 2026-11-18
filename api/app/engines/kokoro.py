"""Kokoro-82M (ONNX) engine — fast CPU quality TTS.

English-first with partial multilingual support (es, fr, hi, it, pt, ja, zh).
Model + voice files are auto-downloaded into STORAGE_PATH/models on first use
(can be disabled with KOKORO_AUTO_DOWNLOAD=false).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from app.config import settings
from app.engines.base import AudioChunk, EngineUnavailable, TTSEngine, VoiceInfo

logger = logging.getLogger("bohurupi.engines.kokoro")

MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx"
)
VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin"
)
# Verified mirror if GitHub is unreachable:
#   https://huggingface.co/ExNihilus/kokoro-onnx/resolve/main/kokoro-v1.0.onnx
#   https://huggingface.co/ExNihilus/kokoro-onnx/resolve/main/voices-v1.0.bin

# Bohurupi voice id -> (kokoro native voice, gender)
KOKO_VOICES: dict[str, tuple[str, str]] = {
    "kokoro:af-heart": ("af_heart", "female"),
    "kokoro:af-bella": ("af_bella", "female"),
    "kokoro:af-nicole": ("af_nicole", "female"),
    "kokoro:am-adam": ("am_adam", "male"),
    "kokoro:am-michael": ("am_michael", "male"),
    "kokoro:bf-emma": ("bf_emma", "female"),
    "kokoro:bm-george": ("bm_george", "male"),
}

# Kokoro v1.0 language mix codes it can handle reasonably
KOKO_LANGS = {"en", "es", "fr", "hi", "it", "pt", "ja", "zh"}
KOKO_LANG_CODES = {
    "en": "en-us",
    "es": "es",
    "fr": "fr-fr",
    "hi": "hi",
    "it": "it",
    "pt": "pt-br",
    "ja": "ja",
    "zh": "zh",
}

KOKO_VOICE_PRESETS: list[dict] = [
    {
        "id": vid,
        "name": f"Kokoro · {native.split('_')[-1].capitalize()} ({gender[0].upper()})",
        "engine": "kokoro",
        "native_voice_id": native,
        "languages": sorted(KOKO_LANGS),
        "gender": gender,
        "styles": ["neutral", "warm"],
    }
    for vid, (native, gender) in KOKO_VOICES.items()
]


def _models_dir() -> Path:
    p = Path(settings.storage_path) / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


class KokoroEngine(TTSEngine):
    name = "kokoro"
    quality_rank = 10
    _kokoro = None
    _loading = False
    _failed = False

    def healthy(self) -> bool:
        return not KokoroEngine._failed

    def supports(self, lang: str) -> bool:
        return lang in KOKO_LANGS

    def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(
                id=vid,
                name=native.replace("_", " ").title(),
                engine="kokoro",
                native_voice_id=native,
                languages=sorted(KOKO_LANGS),
                gender=gender,
                styles=["neutral", "warm"],
            )
            for vid, (native, gender) in KOKO_VOICES.items()
        ]

    async def warmup(self) -> None:
        try:
            await asyncio.to_thread(self._ensure_loaded)
        except Exception as e:  # model download failure must not take the API down
            KokoroEngine._failed = True
            logger.warning("Kokoro warmup failed (%s); falling back to other engines", e)

    def _ensure_loaded(self):
        if KokoroEngine._kokoro is not None:
            return KokoroEngine._kokoro
        models = _models_dir()
        model_path = models / "kokoro-v1.0.onnx"
        voices_path = models / "voices-v1.0.bin"

        if settings.kokoro_auto_download:
            _download(MODEL_URL, model_path)
            _download(VOICES_URL, voices_path)

        if not model_path.exists() or not voices_path.exists():
            raise EngineUnavailable(
                "Kokoro model files missing; set KOKORO_AUTO_DOWNLOAD=true or add them manually"
            )

        from kokoro_onnx import Kokoro

        logger.info("Loading Kokoro ONNX model ...")
        KokoroEngine._kokoro = Kokoro(str(model_path), str(voices_path))
        return KokoroEngine._kokoro

    async def synthesize(
        self,
        text: str,
        lang: str,
        voice_id: str,
        speed: float = 1.0,
        style: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        native_voice = KOKO_VOICES.get(voice_id, ("af_heart", "female"))[0]
        kokoro_lang = KOKO_LANG_CODES.get(lang, "en-us")

        try:
            kokoro = await asyncio.to_thread(self._ensure_loaded)
        except Exception as e:
            KokoroEngine._failed = True
            raise EngineUnavailable(str(e)) from e

        samples, sample_rate = await asyncio.to_thread(
            kokoro.create, text, voice=native_voice, speed=speed, lang=kokoro_lang
        )
        import numpy as np

        pcm16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        step = sample_rate // 5 * 2  # ~0.2 s chunks
        for i in range(0, len(pcm16), step):
            yield AudioChunk(pcm=pcm16[i : i + step], sample_rate=sample_rate)

    def quality_score(self, lang: str) -> float:
        return 0.95 if lang == "en" else 0.6


def _download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    import httpx

    logger.info("Downloading %s -> %s", url, dest)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.Client(timeout=None, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(1 << 20):
                    f.write(chunk)
    tmp.rename(dest)
