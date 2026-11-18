"""Bohurupi FastAPI application entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, audio, auth, chat, meta, stt, voices, ws
from app.config import settings


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db.session import init_db
    from app.engines.kokoro import KokoroEngine
    from app.engines.registry import get_registry

    init_db()
    # warm Kokoro in the background (model download/load must not block boot)
    registry = get_registry()
    for engine in registry.engines:
        if isinstance(engine, KokoroEngine):
            asyncio.create_task(engine.warmup())
    yield


def create_app() -> FastAPI:
    _setup_logging()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.env != "prod" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(meta.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(voices.router)
    app.include_router(stt.router)
    app.include_router(audio.router)
    app.include_router(admin.router)
    app.include_router(ws.router)

    return app


app = create_app()
