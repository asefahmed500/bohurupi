"""Outbound webhook automation.

Real HTTP deliveries, HMAC-SHA256 signed, with a delivery log. Events are
emitted from actual app actions (messages, tickets, voice training/moderation).
No external SaaS required — any HTTP endpoint can receive them.
"""

import hashlib
import hmac
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx
from sqlmodel import Session, select

from app.agent.web_tools import _safe_url
from app.config import settings
from app.db.models import Webhook, WebhookDelivery
from app.db.session import engine

logger = logging.getLogger("bohurupi.automation")
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bohurupi-webhook")

EVENTS = (
    "message.created",
    "ticket.created",
    "voice.trained",
    "voice.moderated",
    "conversation.deleted",
)


def deliver(webhook: Webhook, event: str, payload: dict) -> WebhookDelivery:
    """Synchronous signed delivery (used by the test endpoint and worker)."""
    delivery = WebhookDelivery(webhook_id=webhook.id, event=event)
    body = json.dumps(
        {"event": event, "data": payload, "at": datetime.now(UTC).isoformat()},
        ensure_ascii=False,
    ).encode("utf-8")
    if not (settings.webhook_allow_private or _safe_url(webhook.url)):
        delivery.error = "Only public http(s) URLs are allowed"
        with Session(engine) as session:
            session.add(delivery)
            session.commit()
            session.refresh(delivery)
        return delivery
    signature = "sha256=" + hmac.new(webhook.secret.encode(), body, hashlib.sha256).hexdigest()
    try:
        with httpx.Client(timeout=settings.webhook_timeout_s) as client:
            response = client.post(
                webhook.url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Bohurupi-Event": event,
                    "X-Bohurupi-Signature": signature,
                },
            )
        delivery.status_code = response.status_code
        delivery.ok = 200 <= response.status_code < 300
        if not delivery.ok:
            delivery.error = response.text[:300]
    except Exception as e:
        delivery.error = f"{type(e).__name__}: {str(e)[:200]}"
    with Session(engine) as session:
        session.add(delivery)
        session.commit()
        session.refresh(delivery)
    return delivery


def emit_event(event: str, payload: dict) -> int:
    """Fan out an event to every subscribed active webhook.

    Synchronous and safe from both async endpoints and sync code (no running
    event loop required). Deliveries run in a small worker pool so requests
    never wait on external endpoints.
    """
    if event not in EVENTS:
        return 0
    with Session(engine) as session:
        hooks = session.exec(select(Webhook).where(Webhook.is_active == True)).all()  # noqa: E712
        targets = [
            Webhook(
                id=h.id,
                url=h.url,
                secret=h.secret,
                owner_id=h.owner_id,
                events=h.events,
            )
            for h in hooks
            if event in (h.events or [])
        ]
    for hook in targets:
        _executor.submit(deliver, hook, event, payload)
    return len(targets)
