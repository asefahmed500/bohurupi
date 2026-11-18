"""TTS engine contract (PRD §2.6).

Every engine implements this interface, so adding a new engine is a single file.
Engines normalize output to mono 16-bit PCM chunks so the API layer and the
browser audio queue never care about the engine internals.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from pydantic import BaseModel


@dataclass
class AudioChunk:
    """A chunk of mono signed 16-bit little-endian PCM."""

    pcm: bytes
    sample_rate: int


class VoiceInfo(BaseModel):
    id: str  # Bohurupi voice id (stable string, e.g. "edge:bn-BD-NabanitaNeural")
    name: str
    engine: str
    native_voice_id: str = ""
    languages: list[str]  # ISO 639-1 codes
    gender: str | None = None
    styles: list[str] = []
    clonable: bool = False


class EngineUnavailable(Exception):
    """Raised when an engine cannot serve a request (down, warming, disabled)."""


class NoEngineForLanguage(Exception):
    def __init__(self, lang: str):
        self.lang = lang
        super().__init__(f"No healthy engine supports language '{lang}'")


class TTSEngine(ABC):
    name: str
    quality_rank: int = 0  # lower = higher quality

    # ---- lifecycle ----
    @abstractmethod
    def healthy(self) -> bool:
        """True if the engine can serve requests right now."""

    async def warmup(self) -> None:
        """Optional: load models / fetch voice lists."""

    # ---- catalog ----
    @abstractmethod
    def supports(self, lang: str) -> bool: ...

    @abstractmethod
    def list_voices(self) -> list[VoiceInfo]: ...

    # ---- synthesis ----
    @abstractmethod
    def synthesize(
        self,
        text: str,
        lang: str,
        voice_id: str,
        speed: float = 1.0,
        style: str | None = None,
    ) -> AsyncIterator[AudioChunk]:
        """Yield PCM chunks for the given text."""

    # ---- extras ----
    def quality_score(self, lang: str) -> float:
        """Per-language quality hint used for the scorecard; default flat."""
        return 0.5
