"""Single source of truth for deleting conversations (and all their audio)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from app.config import settings
from app.db.models import AudioAsset, Conversation, Message
from app.db.session import engine
from app.services import storage


def delete_conversation_cascade(session: Session, conv: Conversation) -> list[str]:
    """Delete messages + assets + files for one conversation; returns deleted audio ids."""
    message_ids = [
        m
        for m in session.exec(
            select(Message.id).where(Message.conversation_id == conv.id)  # type: ignore[arg-type]
        ).all()
    ]
    audio_ids: list[str] = []
    paths: list[str] = []
    if message_ids:
        assets = session.exec(
            select(AudioAsset).where(AudioAsset.message_id.in_(message_ids))  # type: ignore[union-attr]
        ).all()
        audio_ids = [a.id for a in assets]
        paths = [a.path for a in assets if a.path]
        session.exec(
            sa_delete(AudioAsset).where(AudioAsset.message_id.in_(message_ids))  # type: ignore[union-attr]
        )
        session.exec(
            sa_delete(Message).where(Message.conversation_id == conv.id)  # type: ignore[arg-type]
        )
    for rel in paths:
        (storage.root() / rel).unlink(missing_ok=True)
    session.delete(conv)
    session.commit()
    return audio_ids


def clear_user_history(session: Session, user_id: str) -> int:
    convs = session.exec(
        select(Conversation).where(Conversation.user_id == user_id)  # type: ignore[arg-type]
    ).all()
    for conv in convs:
        delete_conversation_cascade(session, conv)
    return len(convs)


def cleanup_expired_conversations() -> int:
    """Delete conversations older than CHAT_RETENTION_DAYS (0 disables)."""
    days = settings.chat_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with Session(engine) as session:
        expired = session.exec(
            select(Conversation).where(Conversation.updated_at < cutoff)  # type: ignore[operator]
        ).all()
        for conv in expired:
            delete_conversation_cascade(session, conv)
        return len(expired)
