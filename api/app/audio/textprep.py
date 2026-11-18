"""Sentence splitting and light text normalization for TTS (PRD §2.3 text-prep)."""

import re

# Sentence enders: latin . ! ? ; Indic dari . . ; CJK . ! ?
_ENDERS = ".!?।॥。！？"
_BREAK_SPACE = re.compile(rf'[{_ENDERS}]+["\'”’)\]]*(?=\s|$)')
_BREAK_CJK = re.compile(rf"[।॥。！？](?=[^\s{_ENDERS}])")

_WS_RE = re.compile(r"\s+")
URL_RE = re.compile(r"https?://\S+")


def normalize(text: str) -> str:
    """Whitespace cleanup + URL flattening for speech."""
    text = URL_RE.sub(" link ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def split_sentences(text: str, max_chars: int = 300) -> list[str]:
    """Split into sentences across scripts; hard-split overlong runs."""
    text = normalize(text)
    if not text:
        return []

    # insert line breaks at sentence boundaries (two passes: spaced + CJK)
    marked = _BREAK_SPACE.sub(lambda m: m.group(0) + "\n", text)
    marked = _BREAK_CJK.sub(lambda m: m.group(0) + "\n", marked)

    parts = [p.strip() for p in marked.split("\n") if p.strip()]

    out: list[str] = []
    for s in parts:
        if len(s) <= max_chars:
            out.append(s)
            continue
        # hard split on spaces for very long sentences
        words, cur = s.split(" "), ""
        for w in words:
            if len(cur) + len(w) + 1 > max_chars and cur:
                out.append(cur.strip())
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur.strip():
            out.append(cur.strip())
    return [s for s in out if s]


def est_duration(text: str, chars_per_second: float = 14.0) -> float:
    """Rough duration estimate for progress UX."""
    return max(0.4, len(text) / chars_per_second)
