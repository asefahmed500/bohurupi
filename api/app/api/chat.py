"""Conversations, chat (SSE streaming) and re-speak endpoints (PRD §2.8)."""

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db.models import AudioAsset, Conversation, Message, User
from app.db.session import get_session
from app.deps import get_current_user
from app.services import cache as cache_svc
from app.services.chat import stream_chat, stream_respeak

logger = logging.getLogger("bohurupi.api.chat")

router = APIRouter(tags=["chat"])


# ---- schemas ----


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=120)
    default_lang: str = "auto"
    default_voice_id: str = ""


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    default_lang: str | None = None
    default_voice_id: str | None = None


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    out_lang: str = "auto"
    voice_id: str = ""
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    style: str | None = None
    effect: str | None = None


class RespeakIn(BaseModel):
    voice_id: str
    lang: str = ""
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    style: str | None = None
    effect: str | None = None
    pitch_semitones: float = Field(default=0.0, ge=-6.0, le=6.0)


# ---- helpers ----


def _get_own_conversation(
    conv_id: str, user: User, session: Session
) -> Conversation:
    conv = session.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


def _get_own_message(message_id: str, user: User, session: Session) -> Message:
    msg = session.get(Message, message_id)
    if msg is None or msg.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    conv = session.get(Conversation, msg.conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    return msg


def _sse(gen):
    async def wrapper():
        async for frame in gen:
            yield f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"

    return StreamingResponse(wrapper(), media_type="text/event-stream")


# ---- conversations CRUD ----


@router.get("/conversations")
def list_conversations(
    user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    rows = session.exec(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())  # type: ignore[union-attr]
        .limit(100)
    ).all()
    return {"conversations": rows}


@router.post("/conversations", status_code=201)
def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    conv = Conversation(user_id=user.id, **body.model_dump())
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv


@router.get("/conversations/{conv_id}")
def get_conversation(
    conv_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    conv = _get_own_conversation(conv_id, user, session)
    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())  # type: ignore[union-attr]
        .limit(500)
    ).all()
    audio = session.exec(
        select(AudioAsset).where(
            AudioAsset.message_id.in_([m.id for m in messages])  # type: ignore[union-attr]
        )
    ).all()
    audio_by_msg: dict[str, list] = {}
    for a in audio:
        if a.message_id:
            audio_by_msg.setdefault(a.message_id, []).append(a)
    return {
        "conversation": conv,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "text": m.text,
                "lang": m.lang,
                "translations": m.translations,
                "created_at": m.created_at,
                "audio": audio_by_msg.get(m.id, []),
            }
            for m in messages
        ],
    }


@router.patch("/conversations/{conv_id}")
def patch_conversation(
    conv_id: str,
    body: ConversationPatch,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    conv = _get_own_conversation(conv_id, user, session)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(conv, field, value)
    conv.updated_at = datetime.now(UTC)
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(
    conv_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    conv = _get_own_conversation(conv_id, user, session)
    from app.services import storage

    messages = session.exec(
        select(Message).where(Message.conversation_id == conv.id)
    ).all()
    for m in messages:
        for asset in session.exec(
            select(AudioAsset).where(AudioAsset.message_id == m.id)
        ).all():
            storage.audio_path(asset.id).unlink(missing_ok=True)
            session.delete(asset)
        session.delete(m)
    session.delete(conv)
    session.commit()


# ---- chat (SSE) ----


@router.post("/chat")
def chat(
    body: ChatIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not cache_svc.allow_rate(user.id, "chat", 60, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many messages")
    if not cache_svc.check_quota(user.id, user.plan, len(body.text)):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "Daily voice quota reached for your plan. Upgrade to continue.",
        )

    if body.conversation_id:
        conv = _get_own_conversation(body.conversation_id, user, session)
    else:
        conv = Conversation(
            user_id=user.id,
            title=body.text[:60] + ("…" if len(body.text) > 60 else ""),
        )
        session.add(conv)
        session.commit()
        session.refresh(conv)

    voice_id = body.voice_id or conv.default_voice_id or _default_voice(session, user)
    out_lang = body.out_lang if body.out_lang != "auto" else conv.default_lang

    return _sse(
        stream_chat(
            session,
            conv,
            user.id,
            body.text,
            out_lang=out_lang or "auto",
            voice_id=voice_id,
            speed=body.speed,
            style=body.style,
            effect=body.effect,
        )
    )


def _default_voice(session: Session, user: User) -> str:
    from app.db.models import Setting

    row = session.get(Setting, user.id)
    return (row.default_voice_id if row else "") or "kokoro:af-heart"


# ---- re-speak (FR-4) ----


@router.post("/messages/{message_id}/respeak")
def respeak(
    message_id: str,
    body: RespeakIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    msg = _get_own_message(message_id, user, session)
    if not cache_svc.allow_rate(user.id, "respeak", 60, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests")
    if not cache_svc.check_quota(user.id, user.plan, len(msg.text)):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "Daily voice quota reached for your plan.",
        )
    return _sse(
        stream_respeak(
            session,
            msg,
            user.id,
            voice_id=body.voice_id,
            lang=body.lang,
            speed=body.speed,
            style=body.style,
            effect=body.effect,
            pitch_semitones=body.pitch_semitones,
        )
    )
