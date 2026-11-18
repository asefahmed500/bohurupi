"""Storage helpers: paths, WAV IO."""

import io
import wave
from pathlib import Path

from app.config import settings

AUDIO_DIR = "audio"
SAMPLES_DIR = "samples"
MODELS_DIR = "models"


def root() -> Path:
    p = Path(settings.storage_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def subdir(name: str) -> Path:
    p = root() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def audio_path(asset_id: str) -> Path:
    return subdir(AUDIO_DIR) / f"{asset_id}.wav"


def write_wav(pcm: bytes, sample_rate: int, dest: Path) -> None:
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)


def read_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate()


def pcm_duration(pcm: bytes, sample_rate: int) -> float:
    return len(pcm) / (2 * sample_rate) if sample_rate else 0.0


def pcm_to_wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()
