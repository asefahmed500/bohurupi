"""Audio asset streaming/download + watermark detection (FR-7)."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.audio import watermark
from app.db.models import AudioAsset, Conversation, Message, User
from app.db.session import get_session
from app.deps import get_current_user, require_admin
from app.services import storage

router = APIRouter(tags=["audio"])


def _get_accessible_asset(audio_id: str, user: User, session: Session) -> AudioAsset:
    asset = session.get(AudioAsset, audio_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audio not found")
    if user.role == "admin":
        return asset
    # ownership: direct user_id, or via message -> conversation
    if asset.user_id == user.id:
        return asset
    if asset.message_id:
        msg = session.get(Message, asset.message_id)
        conv = session.get(Conversation, msg.conversation_id) if msg else None
        if conv is not None and conv.user_id == user.id:
            return asset
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Audio not found")


@router.get("/audio/{audio_id}")
def stream_audio(
    audio_id: str,
    download: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    asset = _get_accessible_asset(audio_id, user, session)
    path = storage.root() / asset.path
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "Audio file missing from storage")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={
            "Content-Disposition": (
                f'attachment; filename="bohurupi-{asset.id}.wav"'
                if download
                else "inline"
            ),
            "Cache-Control": "private, max-age=31536000",
        },
    )


@router.get("/audio/{audio_id}/detect")
def detect_watermark(
    audio_id: str,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    asset = session.get(AudioAsset, audio_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audio not found")
    path = storage.root() / asset.path
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "Audio file missing")
    pcm, sr = storage.read_wav(path)
    result = watermark.detect(pcm, sr)
    return {"audio_id": asset.id, "watermark_id": asset.watermark_id, **result}
