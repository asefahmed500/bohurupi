"""Edge TTS engine — wide language coverage (all 20 launch languages incl. Bangla).

Uses the unofficial Microsoft Edge read-aloud endpoint (see PRD licensing note:
treat as a coverage/convenience engine, not the core quality dependency).
MP3 output is decoded to mono PCM via soundfile.
"""

import asyncio
import io
import logging
from collections.abc import AsyncIterator

from app.engines.base import AudioChunk, TTSEngine, VoiceInfo
from app.i18n import LANGUAGES

logger = logging.getLogger("bohurupi.engines.edge")

# Curated per-language default voices (stable ids, no boot-time network call).
# Format: language -> (female voice id, male voice id)
EDGE_VOICE_MAP: dict[str, tuple[str, str]] = {
    "bn": ("bn-BD-NabanitaNeural", "bn-BD-PradeepNeural"),
    "en": ("en-US-AriaNeural", "en-US-GuyNeural"),
    "hi": ("hi-IN-SwaraNeural", "hi-IN-MadhurNeural"),
    "ur": ("ur-PK-UzmaNeural", "ur-PK-AsadNeural"),
    "ar": ("ar-SA-ZariyahNeural", "ar-SA-HamedNeural"),
    "es": ("es-ES-ElviraNeural", "es-ES-AlvaroNeural"),
    "fr": ("fr-FR-DeniseNeural", "fr-FR-HenriNeural"),
    "de": ("de-DE-KatjaNeural", "de-DE-ConradNeural"),
    "pt": ("pt-BR-FranciscaNeural", "pt-BR-AntonioNeural"),
    "ru": ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"),
    "tr": ("tr-TR-EmelNeural", "tr-TR-AhmetNeural"),
    "zh": ("zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"),
    "ja": ("ja-JP-NanamiNeural", "ja-JP-KeitaNeural"),
    "ko": ("ko-KR-SunHiNeural", "ko-KR-InJoonNeural"),
    "it": ("it-IT-ElsaNeural", "it-IT-DiegoNeural"),
    "nl": ("nl-NL-ColetteNeural", "nl-NL-MaartenNeural"),
    "pl": ("pl-PL-ZofiaNeural", "pl-PL-MarekNeural"),
    "id": ("id-ID-GadisNeural", "id-ID-ArdiNeural"),
    "ta": ("ta-IN-PallaviNeural", "ta-IN-ValluvarNeural"),
    "vi": ("vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"),
    "af": ("af-ZA-AdriNeural", "af-ZA-WillemNeural"),
    "am": ("am-ET-MekdesNeural", "am-ET-AmehaNeural"),
    "az": ("az-AZ-BanuNeural", "az-AZ-BabekNeural"),
    "bg": ("bg-BG-KalinaNeural", "bg-BG-BorislavNeural"),
    "bs": ("bs-BA-VesnaNeural", "bs-BA-GoranNeural"),
    "ca": ("ca-ES-JoanaNeural", "ca-ES-EnricNeural"),
    "cs": ("cs-CZ-VlastaNeural", "cs-CZ-AntoninNeural"),
    "da": ("da-DK-ChristelNeural", "da-DK-JeppeNeural"),
    "el": ("el-GR-AthinaNeural", "el-GR-NestorasNeural"),
    "fi": ("fi-FI-NooraNeural", "fi-FI-HarriNeural"),
    "fil": ("fil-PH-BlessicaNeural", "fil-PH-AngeloNeural"),
    "he": ("he-IL-HilaNeural", "he-IL-AvriNeural"),
    "hr": ("hr-HR-GabrijelaNeural", "hr-HR-SreckoNeural"),
    "hu": ("hu-HU-NoemiNeural", "hu-HU-TamasNeural"),
    "is": ("is-IS-GudrunNeural", "is-IS-GunnarNeural"),
    "ka": ("ka-GE-EkaNeural", "ka-GE-GiorgiNeural"),
    "kk": ("kk-KZ-AigulNeural", "kk-KZ-DauletNeural"),
    "kn": ("kn-IN-SapnaNeural", "kn-IN-GaganNeural"),
    "lt": ("lt-LT-OnaNeural", "lt-LT-LeonasNeural"),
    "lv": ("lv-LV-EveritaNeural", "lv-LV-NilsNeural"),
    "mk": ("mk-MK-MarijaNeural", "mk-MK-AleksandarNeural"),
    "mr": ("mr-IN-AarohiNeural", "mr-IN-ManoharNeural"),
    "ms": ("ms-MY-YasminNeural", "ms-MY-OsmanNeural"),
    "ne": ("ne-NP-HemkalaNeural", "ne-NP-SagarNeural"),
    "nb": ("nb-NO-PernilleNeural", "nb-NO-FinnNeural"),
    "ro": ("ro-RO-AlinaNeural", "ro-RO-EmilNeural"),
    "sk": ("sk-SK-ViktoriaNeural", "sk-SK-LukasNeural"),
    "sq": ("sq-AL-AnilaNeural", "sq-AL-IlirNeural"),
    "sr": ("sr-RS-SophieNeural", "sr-RS-NicholasNeural"),
    "sv": ("sv-SE-SofieNeural", "sv-SE-MattiasNeural"),
    "sw": ("sw-KE-ZuriNeural", "sw-KE-RafikiNeural"),
    "te": ("te-IN-ShrutiNeural", "te-IN-MohanNeural"),
    "th": ("th-TH-PremwadeeNeural", "th-TH-NiwatNeural"),
    "uk": ("uk-UA-PolinaNeural", "uk-UA-OstapNeural"),
    "uz": ("uz-UZ-MadinaNeural", "uz-UZ-SardorNeural"),
}

_VOICES: list[VoiceInfo] = [
    VoiceInfo(
        id=f"edge:{female.split('-Neural')[0].lower()}-f",
        name=f"Edge {lang.native} · Female",
        engine="edge",
        native_voice_id=female,
        languages=[code],
        gender="female",
        styles=["neutral", "calm"],
    )
    for code, lang in LANGUAGES.items()
    for female, _ in [EDGE_VOICE_MAP[code]]
] + [
    VoiceInfo(
        id=f"edge:{male.split('-Neural')[0].lower()}-m",
        name=f"Edge {lang.native} · Male",
        engine="edge",
        native_voice_id=male,
        languages=[code],
        gender="male",
        styles=["neutral", "calm"],
    )
    for code, lang in LANGUAGES.items()
    for _, male in [EDGE_VOICE_MAP[code]]
]

# Seeded into the DB on first boot (id -> display catalog)
EDGE_VOICE_PRESETS: list[dict] = [
    {
        "id": v.id,
        "name": v.name,
        "engine": "edge",
        "native_voice_id": v.native_voice_id,
        "languages": v.languages,
        "gender": v.gender,
        "styles": v.styles,
    }
    for v in _VOICES
]


def resolve_edge_voice(voice_id: str) -> str | None:
    """Map a Bohurupi edge voice id to the native Microsoft voice id."""
    for v in _VOICES:
        if v.id == voice_id:
            return v.native_voice_id
    return None


class EdgeEngine(TTSEngine):
    name = "edge"
    quality_rank = 90  # coverage engine — used last in the fallback chain
    _failures = 0

    def healthy(self) -> bool:
        return EdgeEngine._failures < 5

    def supports(self, lang: str) -> bool:
        return lang in EDGE_VOICE_MAP

    def list_voices(self) -> list[VoiceInfo]:
        return _VOICES

    async def synthesize(
        self,
        text: str,
        lang: str,
        voice_id: str,
        speed: float = 1.0,
        style: str | None = None,
    ) -> AsyncIterator[AudioChunk]:

        import edge_tts

        native = resolve_edge_voice(voice_id) or EDGE_VOICE_MAP.get(lang, ("en-US-AriaNeural",))[0]
        rate_pct = max(-50, min(100, int(round((speed - 1.0) * 100))))
        rate_str = f"{rate_pct:+d}%"

        try:
            communicate = edge_tts.Communicate(text, native, rate=rate_str)
            mp3 = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3.extend(chunk["data"])
        except Exception:
            EdgeEngine._failures += 1
            raise

        pcm, sr = await asyncio.to_thread(_decode_audio, bytes(mp3))
        EdgeEngine._failures = 0
        step = 4800 * 2  # ~0.2 s chunks at 24 kHz
        for i in range(0, len(pcm), step):
            yield AudioChunk(pcm=pcm[i : i + step], sample_rate=sr)

    def quality_score(self, lang: str) -> float:
        return 0.7


def _decode_audio(data: bytes) -> tuple[bytes, int]:
    """Decode compressed audio bytes to (mono int16 pcm bytes, sample_rate)."""
    import numpy as np
    import soundfile as sf

    x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    mono = x.mean(axis=1)
    pcm16 = (np.clip(mono, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    return pcm16, int(sr)
