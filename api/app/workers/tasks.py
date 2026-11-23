"""ARQ worker: background TTS jobs (read-aloud documents, batch renders)."""

import logging
from contextlib import asynccontextmanager

from arq.cron import cron
from sqlmodel import Session, select

from app.config import settings
from app.db.models import Voice
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


async def train_voice_job(ctx: dict, payload: dict) -> dict:
    """Learn a voice-adaptation profile from the owner's consented samples."""
    from app.services.voice_profile import train_voice

    voice_id = payload["voice_id"]
    with Session(engine) as session:
        try:
            job = train_voice(session, voice_id)
            return {
                "job_id": job.id,
                "voice_id": voice_id,
                "status": "ready",
                "version": job.version,
            }
        except Exception as e:
            logger.exception("Voice training failed for %s", voice_id)
            from app.db.models import VoiceTrainingJob

            failed = VoiceTrainingJob(voice_id=voice_id, status="failed", error=str(e)[:500])
            session.add(failed)
            session.commit()
            return {"voice_id": voice_id, "status": "failed", "error": str(e)[:200]}


async def nightly_cleanup(ctx: dict) -> dict:
    from app.services.conversation_cleanup import cleanup_expired_conversations

    return {"deleted_conversations": cleanup_expired_conversations()}


async def nightly_voice_improvement(ctx: dict) -> dict:
    """Re-train every approved cloned voice once per day (self-improvement)."""
    with Session(engine) as session:
        voices = session.exec(
            select(Voice).where(Voice.is_preset == False, Voice.status == "ready")  # noqa: E712
        ).all()
        ids = [v.id for v in voices]
    for voice_id in ids:
        redis = ctx.get("redis")
        if redis is not None:
            await redis.enqueue_job("train_voice_job", {"voice_id": voice_id})
        else:
            await train_voice_job({}, {"voice_id": voice_id})
    return {"scheduled": len(ids)}


class WorkerSettings:
    functions = [synthesize_job, train_voice_job, nightly_voice_improvement, nightly_cleanup]
    redis_settings = None  # set below from settings
    max_jobs = 4
    job_timeout = 600
    keep_result = 3600
    # daily self-improvement: re-learn each cloned voice's acoustic profile
    cron_jobs = [
        cron(nightly_voice_improvement, hour=3, minute=0, run_at_startup=False),
        cron(nightly_cleanup, hour=4, minute=0, run_at_startup=False),
    ]


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
