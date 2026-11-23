"""Bohurupi FastAPI application entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import admin, audio, auth, automation, chat, meta, stt, support, voices, ws
from app.config import settings
from app.mcp_server import create_mcp_server
from app.security import assert_security_config


class McpApiKeyMiddleware:
    """Reject unauthenticated /mcp traffic when MCP_API_KEY is configured."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/mcp") and settings.mcp_api_key:
            headers = dict(scope.get("headers", []))
            supplied = headers.get(b"x-mcp-api-key", b"").decode("utf-8", "ignore")
            if supplied != settings.mcp_api_key:
                body = b'{"detail":"Invalid MCP API key"}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    """Conservative security headers on every HTTP response.

    Pure ASGI (not BaseHTTPMiddleware) so audio streaming and WebSockets pass
    through untouched. Deliberately no CSP: /docs (dev only) needs inline
    scripts, and this API serves JSON + audio downloads only.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # websockets pass through untouched
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message["headers"])
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "same-origin")
                message["headers"] = headers.raw
            await send(message)

        await self.app(scope, receive, send_with_headers)


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
    _cleanup_stale_previews()
    from app.services.conversation_cleanup import cleanup_expired_conversations

    cleanup_expired_conversations()
    # warm Kokoro in the background (model download/load must not block boot)
    registry = get_registry()
    for engine in registry.engines:
        if isinstance(engine, KokoroEngine):
            asyncio.create_task(engine.warmup())
    mcp = getattr(app.state, "mcp", None)
    if mcp is None:
        yield
        return
    # MCP 2.x streamable-http needs its session manager running for the app's lifetime
    async with mcp.session_manager.run():
        yield


def _cleanup_stale_previews() -> None:
    """Delete studio-preview WAVs (no linked message) older than 30 days.

    Previews are never referenced by chat history, so without this the audio
    directory grows unboundedly (perf audit finding #10)."""
    import time as _time

    from sqlmodel import Session, select

    from app.db.models import AudioAsset
    from app.db.session import engine
    from app.services import storage

    cutoff = _time.time() - 30 * 86400
    try:
        with Session(engine) as session:
            stale = session.exec(
                select(AudioAsset).where(AudioAsset.message_id.is_(None))  # type: ignore[union-attr]
            ).all()
            removed = 0
            for asset in stale:
                created = asset.created_at.timestamp() if asset.created_at else 0
                if created >= cutoff:
                    continue
                (storage.root() / asset.path).unlink(missing_ok=True)
                session.delete(asset)
                removed += 1
            if removed:
                session.commit()
                logging.getLogger("bohurupi.api").info("Removed %s stale preview assets", removed)
    except Exception:  # pragma: no cover - cleanup must never block boot
        logging.getLogger("bohurupi.api").exception("Preview cleanup failed")


def create_app() -> FastAPI:
    assert_security_config()
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
    # Added after CORS => outermost, so headers land on every response
    # (including CORS errors and preflight).
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(McpApiKeyMiddleware)

    if settings.google_client_id:
        # authlib's OAuth flow stores CSRF state in the Starlette session
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.jwt_secret,
            same_site="lax",
            https_only=settings.env == "prod",
        )

    app.include_router(meta.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(voices.router)
    app.include_router(stt.router)
    app.include_router(audio.router)
    app.include_router(admin.router)
    app.include_router(support.router)
    app.include_router(automation.router)
    app.include_router(ws.router)

    if settings.mcp_api_key:
        mcp = create_mcp_server()
        # the SDK's app already owns the /mcp route — mount it at the root
        app.mount("/", mcp.streamable_http_app(streamable_http_path="/mcp"))
        app.state.mcp = mcp

    return app


app = create_app()
