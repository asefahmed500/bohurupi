"""Engine Registry — the heart of "any language, any voice" (PRD §2.6).

Ordered fallback chain + circuit breaker. If the preferred voice's engine
cannot speak the target language, the next healthy engine that can is used and
the caller is told which engine actually spoke (FR-5).
"""

import logging
import time
from dataclasses import dataclass

from app.engines.base import NoEngineForLanguage, TTSEngine, VoiceInfo

logger = logging.getLogger("bohurupi.registry")

FAILURE_THRESHOLD = 5
COOLDOWN_SECONDS = 60


@dataclass
class PickResult:
    engine: TTSEngine
    voice: VoiceInfo
    fallback_used: bool  # true when the preferred engine/voice could not be used


class CircuitOpen(Exception):
    pass


class Registry:
    def __init__(self, engines: list[TTSEngine]):
        self.engines = sorted(engines, key=lambda e: e.quality_rank)
        self._failures: dict[str, list[float]] = {}
        self._disabled: set[str] = set()

    # ---- health ----
    def record_failure(self, engine_name: str) -> None:
        now = time.monotonic()
        window = [t for t in self._failures.get(engine_name, []) if now - t < COOLDOWN_SECONDS]
        window.append(now)
        self._failures[engine_name] = window
        if len(window) >= FAILURE_THRESHOLD:
            logger.warning("Circuit breaker OPEN for engine '%s'", engine_name)

    def record_success(self, engine_name: str) -> None:
        self._failures.pop(engine_name, None)

    def _breaker_open(self, engine: TTSEngine) -> bool:
        now = time.monotonic()
        window = [t for t in self._failures.get(engine.name, []) if now - t < COOLDOWN_SECONDS]
        self._failures[engine.name] = window
        if engine.name in self._disabled:
            return True
        return len(window) >= FAILURE_THRESHOLD

    def set_enabled(self, engine_name: str, enabled: bool) -> None:
        if enabled:
            self._disabled.discard(engine_name)
        else:
            self._disabled.add(engine_name)

    def is_enabled(self, engine_name: str) -> bool:
        return engine_name not in self._disabled

    # ---- catalog ----
    def find_voice(self, voice_id: str) -> VoiceInfo | None:
        for e in self.engines:
            for v in e.list_voices():
                if v.id == voice_id:
                    return v
        return None

    def list_all_voices(self) -> list[VoiceInfo]:
        out: list[VoiceInfo] = []
        for e in self.engines:
            out.extend(e.list_voices())
        return out

    def engine_status(self) -> list[dict]:
        return [
            {
                "name": e.name,
                "healthy": e.healthy() and not self._breaker_open(e),
                "enabled": self.is_enabled(e.name),
                "quality_rank": e.quality_rank,
                "languages": sorted({code for v in e.list_voices() for code in v.languages}),
            }
            for e in self.engines
        ]

    # ---- selection (FR-5: fallback chain) ----
    def pick(self, lang: str, preferred_voice_id: str = "") -> PickResult:
        """1) preferred voice's engine if it supports lang and is healthy;
        2) any healthy engine supporting lang, by quality."""
        if preferred_voice_id:
            voice = self.find_voice(preferred_voice_id)
            if voice is not None:
                owner = self._engine_by_name(voice.engine)
                if (
                    owner is not None
                    and owner.supports(lang)
                    and owner.healthy()
                    and not self._breaker_open(owner)
                ):
                    return PickResult(engine=owner, voice=voice, fallback_used=False)

        for e in self.engines:
            if e.supports(lang) and e.healthy() and not self._breaker_open(e):
                v = self._default_voice_for(e, lang, preferred_voice_id)
                return PickResult(engine=e, voice=v, fallback_used=bool(preferred_voice_id))

        raise NoEngineForLanguage(lang)

    def _engine_by_name(self, name: str) -> TTSEngine | None:
        return next((e for e in self.engines if e.name == name), None)

    def _default_voice_for(self, engine: TTSEngine, lang: str, preferred: str) -> VoiceInfo:
        voices = [v for v in engine.list_voices() if lang in v.languages]
        if not voices:
            raise NoEngineForLanguage(lang)
        for v in voices:
            if v.id == preferred:
                return v
        return voices[0]


def build_registry() -> Registry:
    """Instantiate engines in the order configured via ENGINE_ORDER."""
    from app.config import settings
    from app.engines.edge import EdgeEngine
    from app.engines.kokoro import KokoroEngine

    by_name: dict[str, TTSEngine] = {"kokoro": KokoroEngine(), "edge": EdgeEngine()}
    engines = [by_name[n] for n in settings.engine_order_list if n in by_name]
    for _name, e in by_name.items():
        if e not in engines:
            engines.append(e)
    return Registry(engines)


registry: Registry | None = None


def get_registry() -> Registry:
    global registry
    if registry is None:
        registry = build_registry()
    return registry
