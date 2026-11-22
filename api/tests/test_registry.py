"""Unit tests: registry fallback chain + circuit breaker (PRD §6)."""

import pytest

from app.engines.base import AudioChunk, TTSEngine, VoiceInfo


class FakeEngine(TTSEngine):
    def __init__(self, name, langs, rank, broken=False):
        self.name = name
        self.quality_rank = rank
        self._langs = langs
        self._broken = broken

    def healthy(self):
        return not self._broken

    def supports(self, lang):
        return lang in self._langs

    def list_voices(self):
        return [
            VoiceInfo(
                id=f"{self.name}:{code}",
                name=f"{self.name} {code}",
                engine=self.name,
                languages=list(self._langs),
            )
            for code in sorted(self._langs)
        ]

    async def synthesize(self, text, lang, voice_id, speed=1.0, style=None):
        if self._broken:
            raise RuntimeError("boom")
        yield AudioChunk(pcm=b"\x00\x00", sample_rate=24000)


def _registry():
    from app.engines.registry import Registry

    xtts = FakeEngine("xtts", {"en"}, rank=5)
    kokoro = FakeEngine("kokoro", {"en"}, rank=10)
    edge = FakeEngine("edge", {"en", "bn", "ar"}, rank=90)
    return Registry([edge, kokoro, xtts], persist=False), xtts, kokoro, edge


async def test_prefers_requested_voice_engine():
    reg, xtts, _k, _e = _registry()
    pick = reg.pick("en", "xtts:en")
    assert pick.engine is xtts
    assert pick.fallback_used is False


async def test_falls_back_when_engine_lacks_language():
    reg, _xtts, _k, edge = _registry()
    pick = reg.pick("bn", "xtts:en")  # xtts cannot speak Bangla
    assert pick.engine is edge
    assert pick.fallback_used is True


async def test_no_engine_for_unknown_language():
    reg, *_ = _registry()
    from app.engines.base import NoEngineForLanguage

    with pytest.raises(NoEngineForLanguage):
        reg.pick("xx", "")


async def test_falls_back_on_runtime_failure():
    reg, xtts, kokoro, _edge = _registry()
    pick = reg.pick("en", "xtts:en")
    assert pick.engine is xtts
    for _ in range(5):  # FAILURE_THRESHOLD -> breaker opens
        reg.record_failure("xtts")
    pick2 = reg.pick("en", "xtts:en")
    assert pick2.engine is kokoro
    assert pick2.fallback_used is True


async def test_disable_engine():
    reg, _xtts, kokoro, _edge = _registry()
    reg.set_enabled("kokoro", False)
    pick = reg.pick("en", "kokoro:en")
    assert pick.engine.name != "kokoro"


async def test_engine_status_shape():
    reg, *_ = _registry()
    status = reg.engine_status()
    assert {"name", "healthy", "enabled", "quality_rank", "languages"} <= set(status[0].keys())
