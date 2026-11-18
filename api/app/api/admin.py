"""Role-gated admin: engines, usage analytics, voice moderation, users (FR-9)."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.models import Message, UsageEvent, User, Voice
from app.db.session import get_session
from app.deps import require_admin
from app.engines.registry import get_registry

logger = logging.getLogger("bohurupi.api.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/engines")
def engines(_admin: User = Depends(require_admin)):
    return {"engines": get_registry().engine_status()}


class EnginePatch(BaseModel):
    enabled: bool


@router.post("/engines/{name}")
def patch_engine(
    name: str,
    body: EnginePatch,
    _admin: User = Depends(require_admin),
):
    registry = get_registry()
    if registry._engine_by_name(name) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown engine '{name}'")
    registry.set_enabled(name, body.enabled)
    return {"name": name, "enabled": body.enabled}


@router.get("/usage")
def usage(
    days: int = Query(default=30, ge=1, le=365),
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    since = datetime.now(UTC) - timedelta(days=days)
    events = session.exec(
        select(UsageEvent).where(UsageEvent.created_at >= since)  # type: ignore[arg-type]
    ).all()

    by_day: dict[str, dict] = {}
    by_type: dict[str, dict] = {}
    for e in events:
        day = e.created_at.strftime("%Y-%m-%d")
        d = by_day.setdefault(day, {"chars": 0, "seconds": 0.0, "count": 0})
        d["chars"] += e.chars
        d["seconds"] += e.seconds
        d["count"] += 1
        t = by_type.setdefault(e.type, {"chars": 0, "seconds": 0.0, "count": 0})
        t["chars"] += e.chars
        t["seconds"] += e.seconds
        t["count"] += 1

    return {
        "days": days,
        "totals": {
            "chars": sum(t["chars"] for t in by_type.values()),
            "seconds": sum(t["seconds"] for t in by_type.values()),
            "events": len(events),
        },
        "by_type": by_type,
        "by_day": dict(sorted(by_day.items())),
    }


@router.get("/voices/moderation")
def pending_voices(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(Voice).where(Voice.status == "moderation")).all()
    return {"voices": rows}


class ModerationIn(BaseModel):
    decision: str  # approve | reject


@router.post("/voices/{voice_id}/moderate")
def moderate_voice(
    voice_id: str,
    body: ModerationIn,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    voice = session.get(Voice, voice_id)
    if voice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Voice not found")
    if body.decision == "approve":
        voice.status = "ready"
    elif body.decision == "reject":
        voice.status = "rejected"
        # privacy: reject removes the biometric material
        from app.services import storage

        for p in (voice.sample_path, voice.embedding_path):
            if p:
                (storage.root() / p).unlink(missing_ok=True)
        voice.sample_path = None
        voice.embedding_path = None
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be approve|reject")
    session.add(voice)
    session.commit()
    session.refresh(voice)
    return voice


@router.get("/users")
def users(
    limit: int = Query(default=50, ge=1, le=500),
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(User).order_by(User.created_at.desc()).limit(limit)).all()
    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name,
                "role": u.role,
                "plan": u.plan,
                "created_at": u.created_at,
            }
            for u in rows
        ]
    }


@router.get("/stats")
def stats(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    return {
        "users": len(session.exec(select(User.id)).all()),  # type: ignore[arg-type]
        "conversations": len(session.exec(select(Message.conversation_id).distinct()).all()),  # type: ignore[arg-type]
        "messages": len(session.exec(select(Message.id)).all()),  # type: ignore[arg-type]
    }
