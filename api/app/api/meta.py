"""Public meta endpoints: languages, health, engine status (PRD §2.8)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.agent.llm import llm_ready
from app.audio.stt import is_available
from app.config import settings
from app.engines.registry import get_registry
from app.i18n import language_list

router = APIRouter(tags=["meta"])


class Health(BaseModel):
    ok: bool
    env: str
    llm: bool
    stt: bool
    engines: list[dict]


@router.get("/languages")
async def get_languages():
    return {"languages": language_list()}


@router.get("/health")
async def health():
    registry = get_registry()
    return Health(
        ok=True,
        env=settings.env,
        llm=llm_ready(),
        stt=is_available(),
        engines=registry.engine_status(),
    )


@router.get("/health/engines")
async def engine_health():
    return {"engines": get_registry().engine_status()}
