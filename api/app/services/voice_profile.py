"""Voice adaptation profiles learned from a user's consented samples.

This computes real acoustic measurements (duration, loudness, zero-crossing
rate, spectral centroid, speaking rate) from decrypted samples and stores them
as a per-voice profile. Synthesis uses these measurements to adapt speed and
pitch. This is voice adaptation, NOT neural timbre cloning — the UI/API report
the engine actually used and never pretend a clone spoke.
"""

import io
import json
import logging
from datetime import UTC, datetime

import numpy as np
import soundfile as sf
from sqlmodel import Session

from app.db.models import Voice, VoiceTrainingJob
from app.services import storage
from app.services.crypto import decrypt_file

logger = logging.getLogger("bohurupi.voice_profile")


def _features_from_bytes(data: bytes) -> dict:
    x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    mono = x.mean(axis=1)
    duration = len(mono) / sr
    rms = float(np.sqrt(np.mean(mono**2))) if len(mono) else 0.0
    zcr = float(np.mean(np.abs(np.diff(np.sign(mono))) > 0) / 2) if len(mono) > 1 else 0.0
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) if len(mono) else np.array([0])
    freqs = np.fft.rfftfreq(len(mono), 1 / sr) if len(mono) else np.array([0])
    centroid = float(np.sum(freqs * spectrum) / (np.sum(spectrum) + 1e-9))
    # voiced-burst rate: a real speaking-tempo proxy measured from energy windows
    window = max(1, int(sr * 0.05))
    energies = np.array(
        [float(np.sqrt(np.mean(mono[i : i + window] ** 2))) for i in range(0, len(mono), window)]
    )
    active = energies > max(rms * 0.35, 1e-6)
    bursts = int(np.sum(active[1:] & ~active[:-1]))
    return {
        "duration_s": round(duration, 3),
        "sample_rate": int(sr),
        "rms": round(rms, 5),
        "zcr": round(zcr, 5),
        "spectral_centroid_hz": round(centroid, 2),
        "voiced_bursts_per_s": round(bursts / max(duration, 0.1), 3),
    }


def compute_profile(voice: Voice) -> dict | None:
    """Decrypt the owner's samples and compute an aggregate acoustic profile."""
    paths = [voice.sample_path, voice.embedding_path]
    samples = []
    for rel in paths:
        if not rel:
            continue
        path = storage.root() / rel
        if not path.exists():
            continue
        try:
            samples.append(decrypt_file(path.read_bytes()))
        except Exception:
            logger.warning("Could not decrypt sample for voice %s", voice.id)

    if not samples:
        # fall back to the consent audio rows stored for this voice
        return None
    features = [_features_from_bytes(data) for data in samples]
    aggregate = {
        key: round(float(np.mean([f[key] for f in features])), 5)
        for key in ("duration_s", "rms", "zcr", "spectral_centroid_hz", "voiced_bursts_per_s")
    }
    aggregate["samples_used"] = len(features)
    aggregate["sample_rate"] = features[0]["sample_rate"]
    return aggregate


def train_voice(session: Session, voice_id: str) -> VoiceTrainingJob:
    voice = session.get(Voice, voice_id)
    if voice is None:
        raise ValueError("Voice not found")
    profile = compute_profile(voice)
    if profile is None:
        raise ValueError("No usable consented samples for this voice")

    version = (voice.profile_version or 0) + 1
    path = storage.subdir("samples") / f"{voice.id}_profile_v{version}.json"
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

    job = VoiceTrainingJob(
        voice_id=voice.id,
        status="ready",
        version=version,
        profile_path=str(path.relative_to(storage.root())),
        features=profile,
        finished_at=datetime.now(UTC),
    )
    voice.profile_path = job.profile_path
    voice.profile_version = version
    session.add(job)
    session.add(voice)
    session.commit()
    session.refresh(job)
    return job


def load_profile(voice_id: str) -> dict | None:
    """Read the current profile for a voice (used by the synthesis adapter)."""
    try:
        from app.db.session import engine as db_engine

        with Session(db_engine) as session:
            voice = session.get(Voice, voice_id)
            if voice is None or not voice.profile_path:
                return None
            path = storage.root() / voice.profile_path
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def adaptation_params(profile: dict | None) -> tuple[float, float]:
    """Map measured voice characteristics to modest speed/pitch adjustments."""
    if not profile:
        return 1.0, 0.0
    zcr = float(profile.get("zcr", 0.05))
    rate = float(profile.get("voiced_bursts_per_s", 0.8))
    speed = float(np.clip(0.8 + rate * 0.25, 0.85, 1.15))
    pitch = float(np.clip((zcr - 0.06) * 16, -2.0, 2.0))
    return round(speed, 3), round(pitch, 2)
