"""ARQ worker: background TTS jobs (read-aloud documents, batch renders)."""

import logging
from contextlib import asynccontextmanager

from sqlmodel import Session

from app.config import settings
from app.db.session import engine

logger = logging.getLogger("bohurupi.worker")


async def synthesize_job(ctx: dict, payload: dict) -> dict:
    """Render text to a WAV asset off the request path.

    payload: {text, lang, voice_id, user_id, message_id?, speed?, effect?}
    """
    from app.services.tts import synthesize_to_wav_file

    with Session(engine) as session:
        asset, meta = await synthesize_to_wav_file(
            session,
            text=payload["text"],
            lang=payload["lang"],
            voice_id=payload["voice_id"],
            message_id=payload.get("message_id"),
            user_id=payload["user_id"],
            speed=float(payload.get("speed") or 1.0),
            effect=payload.get("effect"),
        )
        return {
            "audio_id": asset.id,
            "duration": asset.duration,
            "engine": meta.engine,
            "fallback": meta.fallback_used,
        }


class WorkerSettings:
    functions = [synthesize_job]
    redis_settings = None  # set below from settings
    max_jobs = 4
    job_timeout = 600
    keep_result = 3600


def _init_worker_settings() -> None:
    from arq.connections import RedisSettings

    def _parse(url: str) -> RedisSettings:
        from redis import from_url  # noqa: F401

        return RedisSettings.from_dsn(url)

    WorkerSettings.redis_settings = _parse(settings.redis_url)


@asynccontextmanager
async def _lifespan(ctx: dict):
    _init_worker_settings()
    yield


WorkerSettings.on_startup = _lifespan
