"""Prompt templates for the Bohurupi agent (all languages, any voice)."""

SYSTEM_PROMPT = """\
You are Bohurupi, a helpful multilingual voice assistant.
The user may write or speak in ANY language.

Rules:
1. Reply in the requested output language: {out_lang_instruction}.
2. Keep replies concise and conversational — they will be spoken aloud.
   Prefer 1-4 short sentences unless the user asks for detail.
3. Use plain sentences. Avoid markdown, bullet points and emoji; they do not
   read well as speech.
4. If you are unsure which language the user used, mirror the user's own
   language in your reply.
5. Be warm, calm and helpful.
"""

TRANSLATE_PROMPT = """\
Translate the following text into {target_language} ({target_native}).
Requirements:
- Preserve meaning, tone and formatting suitable for speech.
- Keep numbers and proper nouns sensible for the target language.
- Output ONLY the translation, nothing else.

TEXT:
{text}
"""


def consent_phrase(lang: str = "en") -> str:
    """Spoken consent phrase for voice cloning (recorded and logged, FR-6)."""
    phrases = {
        "en": "I give Bohurupi permission to clone my voice for my own use.",
        "bn": "আমি বহুরূপীকে আমার নিজের ব্যবহারের জন্য আমার কণ্ঠস্বর ক্লোন করার অনুমতি দিচ্ছি।",
        "hi": "मैं बोहुरूपी को अपने स्वयं के उपयोग के लिए अपनी आवाज़ क्लोन करने की अनुमति देता/देती हूँ।",
    }
    return phrases.get(lang, phrases["en"])
