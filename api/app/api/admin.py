"""Role-gated admin: engines, usage analytics, voice moderation, users (FR-9)."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
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
    # aggregate in SQL — O(groups) instead of loading every event into memory
    rows = session.exec(
        select(
            func.date(UsageEvent.created_at).label("day"),  # type: ignore[arg-type]
            UsageEvent.type,
            func.count(),
            func.coalesce(func.sum(UsageEvent.chars), 0),
            func.coalesce(func.sum(UsageEvent.seconds), 0.0),
        )
        .where(UsageEvent.created_at >= since)  # type: ignore[arg-type]
        .group_by(func.date(UsageEvent.created_at), UsageEvent.type)  # type: ignore[arg-type]
    ).all()
    totals_row = session.exec(
        select(
            func.count(),
            func.coalesce(func.sum(UsageEvent.chars), 0),
            func.coalesce(func.sum(UsageEvent.seconds), 0.0),
        ).where(UsageEvent.created_at >= since)  # type: ignore[arg-type]
    ).one()

    by_day: dict[str, dict] = {}
    by_type: dict[str, dict] = {}
    for day, ev_type, count, chars, seconds in rows:
        d = by_day.setdefault(str(day), {"chars": 0, "seconds": 0.0, "count": 0})
        d["chars"] += int(chars)
        d["seconds"] += float(seconds)
        d["count"] += int(count)
        t = by_type.setdefault(ev_type, {"chars": 0, "seconds": 0.0, "count": 0})
        t["chars"] += int(chars)
        t["seconds"] += float(seconds)
        t["count"] += int(count)

    return {
        "days": days,
        "totals": {
            "chars": int(totals_row[1]),
            "seconds": float(totals_row[2]),
            "events": int(totals_row[0]),
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

    from app.services.automation import emit_event

    emit_event(
        "voice.moderated",
        {"voice_id": voice.id, "status": voice.status, "decision": body.decision},
    )
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
                "is_active": u.is_active,
                "created_at": u.created_at,
            }
            for u in rows
        ]
    }


class UserPatch(BaseModel):
    role: str | None = None
    plan: str | None = None
    is_active: bool | None = None


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    body: UserPatch,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    """Promote/demote, change plan, enable/disable accounts (FR-9)."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if body.role is not None and body.role not in ("user", "admin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role must be user|admin")
    if body.plan is not None and body.plan not in ("free", "pro", "studio"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "plan must be free|pro|studio")
    if user.id == admin.id and body.is_active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot disable your own account")
    if user.id == admin.id and body.role == "user":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote your own account")
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    session.add(user)
    session.commit()
    session.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "plan": user.plan,
        "is_active": user.is_active,
        "created_at": user.created_at,
    }


@router.get("/stats")
def stats(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
):
    # count aggregates in SQL instead of loading every id into memory
    return {
        "users": session.exec(select(func.count()).select_from(User)).one(),  # type: ignore[arg-type]
        "conversations": session.exec(
            select(func.count(func.distinct(Message.conversation_id)))  # type: ignore[arg-type]
        ).one(),
        "messages": session.exec(select(func.count()).select_from(Message)).one(),  # type: ignore[arg-type]
    }
