"""SQLModel tables (PRD §2.7)."""

import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str | None = None  # null for OAuth-only accounts
    name: str = ""
    role: str = "user"  # user | admin
    plan: str = "free"  # free | pro | studio
    stripe_customer_id: str | None = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=_now)

    conversations: list["Conversation"] = Relationship(back_populates="user")
    voices: list["Voice"] = Relationship(back_populates="owner")
    settings_row: Optional["Setting"] = Relationship(back_populates="user")


class Conversation(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    business_id: str | None = Field(foreign_key="business.id", index=True, default=None)
    title: str = "New conversation"
    default_lang: str = "auto"  # "auto" or ISO code
    default_voice_id: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    user: User = Relationship(back_populates="conversations")
    messages: list["Message"] = Relationship(back_populates="conversation")


class Message(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    conversation_id: str = Field(foreign_key="conversation.id", index=True)
    role: str  # user | assistant | system
    text: str = ""
    lang: str = ""  # detected/used language (ISO code)
    translations: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )  # {lang: translated_text}
    created_at: datetime = Field(default_factory=_now)

    conversation: Conversation = Relationship(back_populates="messages")
    audio: list["AudioAsset"] = Relationship(back_populates="message")


class AudioAsset(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    message_id: str | None = Field(foreign_key="message.id", index=True)
    user_id: str | None = Field(foreign_key="user.id", index=True, default=None)
    voice_id: str = ""
    lang: str = ""
    engine: str = ""
    path: str = ""  # relative to STORAGE_PATH
    duration: float = 0.0  # seconds
    sample_rate: int = 0
    watermark_id: str | None = None
    created_at: datetime = Field(default_factory=_now)

    message: Message | None = Relationship(back_populates="audio")


class Voice(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    owner_id: str | None = Field(foreign_key="user.id", index=True, default=None)
    name: str
    engine: str = ""  # kokoro | edge | xtts | mms | ...
    native_voice_id: str = ""  # engine-specific id (e.g. "bn-BD-NabanitaNeural")
    languages: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    gender: str | None = None
    styles: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    clonable: bool = False
    is_preset: bool = False
    status: str = "ready"  # ready | pending | moderation | rejected
    sample_path: str | None = None  # cloned sample (encrypted at rest)
    embedding_path: str | None = None
    profile_path: str | None = None  # learned voice-adaptation profile
    profile_version: int = 0
    created_at: datetime = Field(default_factory=_now)

    owner: User | None = Relationship(back_populates="voices")
    consents: list["Consent"] = Relationship(back_populates="voice")


class Consent(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    voice_id: str = Field(foreign_key="voice.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    phrase_text: str = ""
    phrase_audio_path: str = ""
    accepted_at: datetime = Field(default_factory=_now)
    ip: str = ""

    voice: Voice = Relationship(back_populates="consents")


class Setting(SQLModel, table=True):
    user_id: str = Field(foreign_key="user.id", primary_key=True)
    theme: str = "system"  # light | dark | system
    default_lang: str = "auto"
    default_voice_id: str = ""
    speed: float = 1.0
    auto_play: bool = True
    captions: bool = True
    engine_pref: str = "quality"  # quality | fast | coverage

    user: User = Relationship(back_populates="settings_row")


class UsageEvent(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    type: str  # tts | stt | llm | clone
    chars: int = 0
    seconds: float = 0.0
    created_at: datetime = Field(default_factory=_now, index=True)


class EngineState(SQLModel, table=True):
    """Admin enable/disable per TTS engine — survives restarts (FR-9)."""

    name: str = Field(primary_key=True)
    enabled: bool = True


class Business(SQLModel, table=True):
    """Tenant for the customer-support agent (one business, many conversations)."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    slug: str = Field(index=True, unique=True)
    system_prompt: str = "You are a concise, helpful customer-support agent."
    languages: list[str] = Field(default_factory=lambda: ["en"], sa_column=Column(JSON))
    is_active: bool = True
    created_at: datetime = Field(default_factory=_now)

    documents: list["KnowledgeDocument"] = Relationship(back_populates="business")
    tickets: list["SupportTicket"] = Relationship(back_populates="business")


class KnowledgeDocument(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    business_id: str = Field(foreign_key="business.id", index=True)
    title: str
    source: str = ""
    content: str
    created_at: datetime = Field(default_factory=_now)

    business: Business = Relationship(back_populates="documents")
    chunks: list["KnowledgeChunk"] = Relationship(back_populates="document")


class KnowledgeChunk(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    document_id: str = Field(foreign_key="knowledgedocument.id", index=True)
    business_id: str = Field(foreign_key="business.id", index=True)
    text: str
    # hashed TF-IDF bag-of-words: {token: weight} — real lexical retrieval
    embedding: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    document: KnowledgeDocument = Relationship(back_populates="chunks")


class SupportTicket(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    business_id: str = Field(foreign_key="business.id", index=True)
    conversation_id: str | None = Field(default=None, foreign_key="conversation.id", index=True)
    customer_email: str = ""
    subject: str
    message: str
    status: str = "open"  # open | escalated | closed
    created_at: datetime = Field(default_factory=_now)

    business: Business = Relationship(back_populates="tickets")


class VoiceTrainingJob(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    voice_id: str = Field(foreign_key="voice.id", index=True)
    status: str = "queued"  # queued | running | ready | failed
    version: int = 1
    profile_path: str | None = None
    features: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None


class Webhook(SQLModel, table=True):
    """Outbound automation: signed HTTP callback on real app events."""

    id: str = Field(default_factory=_uuid, primary_key=True)
    owner_id: str = Field(foreign_key="user.id", index=True)
    url: str
    events: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    secret: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=_now)


class WebhookDelivery(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    webhook_id: str = Field(foreign_key="webhook.id", index=True)
    event: str
    status_code: int | None = None
    ok: bool = False
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
