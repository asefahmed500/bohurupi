"""Automation API: webhook subscriptions, test sends and delivery history."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl
from sqlmodel import Session, select

from app.db.models import User, Webhook, WebhookDelivery
from app.db.session import get_session
from app.deps import get_current_user
from app.services import automation

router = APIRouter(prefix="/automations", tags=["automations"])


class WebhookIn(BaseModel):
    url: HttpUrl
    events: list[str] = Field(default_factory=list)
    is_active: bool = True


class WebhookOut(BaseModel):
    id: str
    url: str
    events: list[str]
    is_active: bool
    secret: str  # shown once on create; safe to display again to the owner


def _out(h: Webhook) -> WebhookOut:
    return WebhookOut(
        id=h.id, url=h.url, events=h.events or [], is_active=h.is_active, secret=h.secret
    )


@router.get("/events")
def list_events(_user: User = Depends(get_current_user)):
    return {"events": list(automation.EVENTS)}


@router.post("/webhooks", status_code=201, response_model=WebhookOut)
def create_webhook(
    body: WebhookIn, user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    unknown = set(body.events) - set(automation.EVENTS)
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown events: {sorted(unknown)}")
    hook = Webhook(
        owner_id=user.id,
        url=str(body.url),
        events=body.events,
        secret=secrets.token_urlsafe(24),
        is_active=body.is_active,
    )
    session.add(hook)
    session.commit()
    session.refresh(hook)
    return _out(hook)


@router.get("/webhooks")
def list_webhooks(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stmt = select(Webhook)
    if user.role != "admin":
        stmt = stmt.where(Webhook.owner_id == user.id)  # type: ignore[arg-type]
    hooks = session.exec(stmt).all()
    return {"webhooks": [_out(h) for h in hooks]}


@router.delete("/webhooks/{hook_id}", status_code=204)
def delete_webhook(
    hook_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    hook = session.get(Webhook, hook_id)
    if hook is None or (hook.owner_id != user.id and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
    for d in session.exec(
        select(WebhookDelivery).where(WebhookDelivery.webhook_id == hook_id)  # type: ignore[arg-type]
    ).all():
        session.delete(d)
    session.delete(hook)
    session.commit()


@router.post("/webhooks/{hook_id}/test")
def test_webhook(
    hook_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    hook = session.get(Webhook, hook_id)
    if hook is None or (hook.owner_id != user.id and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
    result = automation.deliver(
        hook, "message.created", {"test": True, "message": "Bohurupi webhook test"}
    )
    return {"ok": result.ok, "status_code": result.status_code, "error": result.error}


@router.get("/webhooks/{hook_id}/deliveries")
def webhook_deliveries(
    hook_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    hook = session.get(Webhook, hook_id)
    if hook is None or (hook.owner_id != user.id and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
    rows = session.exec(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == hook_id)  # type: ignore[arg-type]
        .order_by(WebhookDelivery.created_at.desc())  # type: ignore[union-attr]
    ).all()
    return {
        "deliveries": [
            {
                "id": d.id,
                "event": d.event,
                "ok": d.ok,
                "status_code": d.status_code,
                "error": d.error,
                "created_at": d.created_at,
            }
            for d in rows
        ]
    }
