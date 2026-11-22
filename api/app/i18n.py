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
        # --- expanded voice library (Edge TTS coverage) ---
        Language("af", "Afrikaans", "Afrikaans"),
        Language("am", "Amharic", "አማርኛ"),
        Language("az", "Azerbaijani", "Azərbaycanca"),
        Language("bg", "Bulgarian", "Български"),
        Language("bs", "Bosnian", "Bosanski"),
        Language("ca", "Catalan", "Català"),
        Language("cs", "Czech", "Čeština"),
        Language("da", "Danish", "Dansk"),
        Language("el", "Greek", "Ελληνικά"),
        Language("fi", "Finnish", "Suomi"),
        Language("fil", "Filipino", "Filipino"),
        Language("he", "Hebrew", "עברית", rtl=True),
        Language("hr", "Croatian", "Hrvatski"),
        Language("hu", "Hungarian", "Magyar"),
        Language("is", "Icelandic", "Íslenska"),
        Language("ka", "Georgian", "ქართული"),
        Language("kk", "Kazakh", "Қазақша"),
        Language("kn", "Kannada", "ಕನ್ನಡ"),
        Language("lt", "Lithuanian", "Lietuvių"),
        Language("lv", "Latvian", "Latviešu"),
        Language("mk", "Macedonian", "Македонски"),
        Language("mr", "Marathi", "मराठी"),
        Language("ms", "Malay", "Bahasa Melayu"),
        Language("nb", "Norwegian", "Norsk bokmål"),
        Language("ne", "Nepali", "नेपाली"),
        Language("ro", "Romanian", "Română"),
        Language("sk", "Slovak", "Slovenčina"),
        Language("sq", "Albanian", "Shqip"),
        Language("sr", "Serbian", "Српски"),
        Language("sv", "Swedish", "Svenska"),
        Language("sw", "Swahili", "Kiswahili"),
        Language("te", "Telugu", "తెలుగు"),
        Language("th", "Thai", "ไทย"),
        Language("uk", "Ukrainian", "Українська"),
        Language("uz", "Uzbek", "Oʻzbekcha"),
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
    # expanded languages supported by the local detector
    "af": "AFRIKAANS",
    "az": "AZERBAIJANI",
    "bg": "BULGARIAN",
    "bs": "BOSNIAN",
    "ca": "CATALAN",
    "cs": "CZECH",
    "da": "DANISH",
    "el": "GREEK",
    "fi": "FINNISH",
    "he": "HEBREW",
    "hr": "CROATIAN",
    "hu": "HUNGARIAN",
    "is": "ICELANDIC",
    "ka": "GEORGIAN",
    "kk": "KAZAKH",
    "lt": "LITHUANIAN",
    "lv": "LATVIAN",
    "mk": "MACEDONIAN",
    "mr": "MARATHI",
    "ms": "MALAY",
    "nb": "NORWEGIAN",  # lingua reports its ISO code as "no"
    "ro": "ROMANIAN",
    "sk": "SLOVAK",
    "sq": "ALBANIAN",
    "sr": "SERBIAN",
    "sv": "SWEDISH",
    "sw": "SWAHILI",
    "te": "TELUGU",
    "th": "THAI",
    "uk": "UKRAINIAN",
}


def is_supported(code: str) -> bool:
    return code in LANGUAGES


def language_list() -> list[dict]:
    return [
        {"code": lang.code, "name": lang.name, "native": lang.native, "rtl": lang.rtl}
        for lang in LANGUAGES.values()
    ]
