"""Voice library, cloning with consent gate (FR-6), deletion (privacy)."""

import io
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import settings
from app.db.models import Consent, User, Voice
from app.db.session import get_session
from app.deps import get_current_user
from app.services import cache as cache_svc
from app.services import storage
from app.services.crypto import decrypt_file, encrypt_file

logger = logging.getLogger("bohurupi.api.voices")

router = APIRouter(prefix="/voices", tags=["voices"])

SAMPLE_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}


class VoiceOut(BaseModel):
    id: str
    name: str
    engine: str
    languages: list[str]
    gender: str | None
    styles: list[str]
    clonable: bool
    is_preset: bool
    status: str
    owner_id: str | None = None

    model_config = {"from_attributes": True}


class ConsentPhraseOut(BaseModel):
    phrase: str
    lang: str


@router.get("")
def list_voices(
    lang: str | None = None,
    gender: str | None = None,
    style: str | None = None,
    engine: str | None = None,
    q: str | None = None,
    mine: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    stmt = select(Voice).where(
        Voice.status.in_(["ready", "pending", "moderation"])  # type: ignore[arg-type]
    )
    rows = session.exec(stmt).all()
    out = []
    for v in rows:
        if mine and (v.is_preset or v.owner_id != user.id):
            continue
        if not mine and v.status != "ready":
            continue  # others only see approved voices
        if lang and lang not in v.languages:
            continue
        if gender and v.gender != gender:
            continue
        if style and style not in v.styles:
            continue
        if engine and v.engine != engine:
            continue
        if q and q.lower() not in v.name.lower():
            continue
        out.append(VoiceOut.model_validate(v))
    return {"voices": out}


@router.get("/consent-phrase")
def consent_phrase(lang: str = "en"):
    from app.agent.prompts import consent_phrase as phrase_for

    return ConsentPhraseOut(phrase=phrase_for(lang), lang=lang)


class CloneOut(BaseModel):
    voice: VoiceOut
    status: str
    note: str


@router.post("/clone", response_model=CloneOut, status_code=201)
async def clone_voice(
    request: Request,
    name: str = Form(..., max_length=80),
    consent: bool = Form(...),
    consent_lang: str = Form("en"),
    consent_phrase_text: str = Form(...),
    sample_lang: str = Form("en"),
    sample: UploadFile = File(...),
    consent_audio: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Voice cloning with the consent gate (FR-6):
    explicit checkbox + phrase match + logged consent + quality check."""
    if not cache_svc.allow_rate(user.id, "clone", 5, 3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Clone rate limit reached")

    from app.agent.prompts import consent_phrase as phrase_for

    expected = phrase_for(consent_lang)
    if not consent:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Consent is required for cloning")
    if consent_phrase_text.strip() != expected:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Typed consent phrase does not match. Copy the phrase exactly.",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    for f in (sample, consent_audio):
        if f.filename and Path(f.filename).suffix.lower() not in SAMPLE_SUFFIXES:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"Unsupported file type: {f.filename}",
            )

    sample_bytes = await sample.read()
    consent_bytes = await consent_audio.read()
    if len(sample_bytes) > max_bytes or len(consent_bytes) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Max upload size is {settings.max_upload_mb} MB",
        )

    quality = _check_sample_quality(sample_bytes)
    if not quality["ok"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, quality["reason"])

    # persist encrypted (privacy: samples encrypted at rest)
    voice = Voice(
        owner_id=user.id,
        name=name.strip(),
        engine="xtts",  # synthesis engine wired by the cloning worker
        languages=[sample_lang],
        gender=None,
        styles=["neutral"],
        clonable=False,
        is_preset=False,
        status="moderation",  # SaaS: goes through moderation before use
    )
    session.add(voice)
    session.commit()
    session.refresh(voice)

    samples_dir = storage.subdir("samples")
    sample_path = samples_dir / f"{voice.id}_sample.bin"
    consent_path = samples_dir / f"{voice.id}_consent.bin"
    sample_path.write_bytes(encrypt_file(sample_bytes))
    consent_path.write_bytes(encrypt_file(consent_bytes))

    voice.sample_path = str(sample_path.relative_to(storage.root()))
    voice.embedding_path = str(consent_path.relative_to(storage.root()))
    session.add(voice)

    session.add(
        Consent(
            voice_id=voice.id,
            user_id=user.id,
            phrase_text=expected,
            phrase_audio_path=voice.embedding_path,
            ip=request.client.host if request.client else "",
        )
    )
    session.commit()
    session.refresh(voice)

    note = (
        "Voice submitted. It must pass moderation before use; you will find it "
        "under 'My voices' with status pending."
        if voice.status == "moderation"
        else "Voice ready."
    )
    return CloneOut(voice=VoiceOut.model_validate(voice), status=voice.status, note=note)


def _check_sample_quality(data: bytes) -> dict:
    """Validate duration (10-30 s), level and clipping (PRD §2.10)."""
    try:
        import numpy as np
        import soundfile as sf

        x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception as e:
        return {"ok": False, "reason": f"Could not read audio file ({e}). Use WAV or MP3."}

    duration = len(x) / sr
    if duration < 10:
        return {
            "ok": False,
            "reason": f"Sample too short ({duration:.1f}s). Record 10-30 seconds.",
        }
    if duration > 30:
        return {
            "ok": False,
            "reason": f"Sample too long ({duration:.1f}s). Keep it under 30 seconds.",
        }

    mono = x.mean(axis=1)
    rms = float(np.sqrt(np.mean(mono**2)))
    if rms < 0.005:
        return {"ok": False, "reason": "Sample is too quiet. Move closer to the microphone."}
    if rms > 0.5:
        return {"ok": False, "reason": "Sample is too loud / distorted. Lower the input volume."}
    clipped = float(np.mean(np.abs(mono) > 0.99))
    if clipped > 0.01:
        return {"ok": False, "reason": "Sample is clipping. Record in a quieter spot."}
    return {"ok": True}


@router.delete("/{voice_id}", status_code=204)
def delete_voice(
    voice_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Delete-my-voice: removes sample, consent audio and embeddings (privacy)."""
    voice = session.get(Voice, voice_id)
    if voice is None or (voice.owner_id != user.id and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Voice not found")
    for p in (voice.sample_path, voice.embedding_path):
        if p:
            (storage.root() / p).unlink(missing_ok=True)
    for c in session.exec(select(Consent).where(Consent.voice_id == voice.id)).all():
        session.delete(c)
    session.delete(voice)
    session.commit()


@router.get("/{voice_id}/sample")
def download_sample(
    voice_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Owner can re-listen to their uploaded sample (decrypted on the fly)."""
    voice = session.get(Voice, voice_id)
    if voice is None or voice.owner_id != user.id or not voice.sample_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Voice not found")
    data = decrypt_file((storage.root() / voice.sample_path).read_bytes())
    from fastapi.responses import Response

    return Response(
        content=data,
        media_type="audio/wav",
        headers={"Content-Disposition": f'attachment; filename="{voice.name}-sample.wav"'},
    )
