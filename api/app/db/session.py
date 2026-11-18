"""Engine setup, session factory, and first-boot seeding."""

import logging

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

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    **_engine_kwargs,
)


def get_session():
    with Session(engine) as session:
        yield session


def init_db() -> None:
    """Create tables (dev fast-path; Alembic owns schema in prod) and seed presets."""
    SQLModel.metadata.create_all(engine)
    _seed_preset_voices()


def _seed_preset_voices() -> None:
    from app.engines.edge import EDGE_VOICE_PRESETS
    from app.engines.kokoro import KOKO_VOICE_PRESETS

    with Session(engine) as session:
        existing = session.exec(select(Voice).where(Voice.is_preset)).first()
        if existing is not None:
            return
        for preset in [*KOKO_VOICE_PRESETS, *EDGE_VOICE_PRESETS]:
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
        logger.info("Seeded preset voices")
