"""Speech-to-text endpoint (FR-1, F2)."""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.audio.stt import is_available, transcribe
from app.config import settings
from app.db.models import User
from app.db.session import get_session
from app.deps import get_current_user
from app.services import cache as cache_svc

logger = logging.getLogger("bohurupi.api.stt")

router = APIRouter(tags=["stt"])


@router.post("/stt")
async def speech_to_text(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    denoise: str | None = Form(None),
    user: User = Depends(get_current_user),
    _session=Depends(get_session),
):
    if not is_available():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Speech recognition is not installed on this deployment (missing 'audio' extra).",
        )
    if not cache_svc.allow_rate(user.id, "stt", 30, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")

    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Max upload size is {settings.max_upload_mb} MB",
        )
    if len(data) < 512:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Audio file is too small")

    denoise_flag = None if denoise is None else denoise.lower() in ("1", "true", "yes", "on")
    result = await _run(data, language, denoise_flag)
    return {
        "text": result.text,
        "language": result.language,
        "confidence": round(result.confidence, 3),
        "denoised": result.denoised,
    }


async def _run(data: bytes, language: str | None, denoise: bool | None = None):
    import asyncio

    try:
        return await asyncio.to_thread(transcribe, data, language, denoise)
    except Exception as e:
        logger.exception("STT failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Speech recognition failed") from e
