"""Engine setup, session factory, and first-boot seeding."""

import logging

from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import settings
from app.db import models  # noqa: F401  (register tables)
from app.db.models import Voice

logger = logging.getLogger("bohurupi.db")

_connect_args = {}
_engine_kwargs: dict = {}

if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    if ":memory:" in settings.database_url:
        _engine_kwargs["poolclass"] = StaticPool


def _enable_sqlite_foreign_keys(dbapi_conn, _record) -> None:
    """Enforce the FKs the schema declares (SQLite ships with them OFF).

    App code cascades manually (chat.py delete_conversation, voices.py
    delete_voice delete children first), so enforcement is safe — it only
    rejects writes that would have created orphan rows silently.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    **_engine_kwargs,
)

if settings.database_url.startswith("sqlite"):
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)


def get_session():
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create tables (dev fast-path; Alembic owns schema in prod) and seed presets."""
    SQLModel.metadata.create_all(engine)
    _seed_preset_voices()
    _seed_demo_user()


def _seed_demo_user() -> None:
    """Dev/staging-only demo account (never admin, never seeded in prod)."""
    from app.config import settings
    from app.db.models import Setting, User
    from app.security import hash_password

    if not settings.demo_enabled:
        return
    with Session(engine) as session:
        existing = session.exec(
            select(User).where(User.email == settings.demo_email.lower())
        ).first()
        if existing is not None:
            return
        user = User(
            email=settings.demo_email.lower(),
            name=settings.demo_name,
            password_hash=hash_password(settings.demo_password),
            role="user",
            plan="free",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        if session.get(Setting, user.id) is None:
            session.add(Setting(user_id=user.id))
            session.commit()
        logger.info("Seeded demo account %s", user.email)


def _seed_preset_voices() -> None:
    from app.engines.edge import EDGE_VOICE_PRESETS
    from app.engines.kokoro import KOKO_VOICE_PRESETS

    presets = [*KOKO_VOICE_PRESETS, *EDGE_VOICE_PRESETS]
    with Session(engine) as session:
        existing_ids = {v.id for v in session.exec(select(Voice)).all()}
        missing = [p for p in presets if p["id"] not in existing_ids]
        if not missing:
            return
        for preset in missing:
            session.add(
                Voice(
                    id=preset["id"],
                    name=preset["name"],
                    engine=preset["engine"],
                    native_voice_id=preset["native_voice_id"],
                    languages=preset["languages"],
                    gender=preset["gender"],
                    styles=preset.get("styles", []),
                    is_preset=True,
                    status="ready",
                )
            )
        session.commit()
        logger.info("Seeded %s new preset voices", len(missing))
