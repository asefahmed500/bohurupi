"""Launch languages (PRD §9.2) with native names and RTL flags.

Shared by the language picker UI (served via GET /languages) and engine mapping.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str  # ISO 639-1
    name: str  # English name
    native: str  # Endonym
    rtl: bool = False


LANGUAGES: dict[str, Language] = {
    lang.code: lang
    for lang in [
        Language("bn", "Bengali", "বাংলা"),
        Language("en", "English", "English"),
        Language("hi", "Hindi", "हिन्दी"),
        Language("ur", "Urdu", "اردو", rtl=True),
        Language("ar", "Arabic", "العربية", rtl=True),
        Language("es", "Spanish", "Español"),
        Language("fr", "French", "Français"),
        Language("de", "German", "Deutsch"),
        Language("pt", "Portuguese", "Português"),
        Language("ru", "Russian", "Русский"),
        Language("tr", "Turkish", "Türkçe"),
        Language("zh", "Chinese", "中文"),
        Language("ja", "Japanese", "日本語"),
        Language("ko", "Korean", "한국어"),
        Language("it", "Italian", "Italiano"),
        Language("nl", "Dutch", "Nederlands"),
        Language("pl", "Polish", "Polski"),
        Language("id", "Indonesian", "Bahasa Indonesia"),
        Language("ta", "Tamil", "தமிழ்"),
        Language("vi", "Vietnamese", "Tiếng Việt"),
    ]
}

# lingua-py uses its own enum names; map ISO codes -> lingua language names
LINGUA_NAMES: dict[str, str] = {
    "bn": "BENGALI",
    "en": "ENGLISH",
    "hi": "HINDI",
    "ur": "URDU",
    "ar": "ARABIC",
    "es": "SPANISH",
    "fr": "FRENCH",
    "de": "GERMAN",
    "pt": "PORTUGUESE",
    "ru": "RUSSIAN",
    "tr": "TURKISH",
    "zh": "CHINESE",
    "ja": "JAPANESE",
    "ko": "KOREAN",
    "it": "ITALIAN",
    "nl": "DUTCH",
    "pl": "POLISH",
    "id": "INDONESIAN",
    "ta": "TAMIL",
    "vi": "VIETNAMESE",
}


def is_supported(code: str) -> bool:
    return code in LANGUAGES


def language_list() -> list[dict]:
    return [
        {"code": lang.code, "name": lang.name, "native": lang.native, "rtl": lang.rtl}
        for lang in LANGUAGES.values()
    ]
