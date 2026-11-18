"""Unit tests: consent gate rules + sample quality checks (FR-6)."""

import io
import wave

import pytest

from app.agent.prompts import consent_phrase
from app.api.voices import _check_sample_quality


def _wav_bytes(seconds: float, sr: int = 16000, amp: float = 0.3) -> bytes:
    import numpy as np

    n = int(seconds * sr)
    t = np.linspace(0, seconds, n, endpoint=False)
    x = (amp * np.sin(2 * np.pi * 220 * t)).astype("float32")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def test_consent_phrase_languages():
    assert "Bohurupi" in consent_phrase("en")
    assert consent_phrase("bn") != consent_phrase("en")
    assert consent_phrase("xx") == consent_phrase("en")  # fallback


def test_sample_ok():
    res = _check_sample_quality(_wav_bytes(15))
    assert res["ok"], res


def test_sample_too_short():
    res = _check_sample_quality(_wav_bytes(3))
    assert not res["ok"]
    assert "short" in res["reason"]


def test_sample_too_long():
    res = _check_sample_quality(_wav_bytes(35))
    assert not res["ok"]
    assert "long" in res["reason"]


def test_sample_too_quiet():
    res = _check_sample_quality(_wav_bytes(15, amp=0.001))
    assert not res["ok"]
    assert "quiet" in res["reason"]


def test_sample_clipping():
    res = _check_sample_quality(_wav_bytes(15, amp=1.0))
    assert not res["ok"]


def test_sample_garbage():
    res = _check_sample_quality(b"not audio at all")
    assert not res["ok"]


@pytest.mark.parametrize("lang", ["en", "bn", "hi"])
def test_consent_phrase_stable(lang):
    assert len(consent_phrase(lang)) > 20
