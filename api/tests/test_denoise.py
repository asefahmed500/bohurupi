"""Noise-suppression tests: real numerical signal measurements."""

import numpy as np

from app.audio.denoise import denoise_samples


def test_denoise_reduces_stationary_noise():
    sr = 16000
    t = np.arange(sr) / sr
    speech = 0.35 * np.sin(2 * np.pi * 200 * t)
    noise = np.random.default_rng(7).normal(0, 0.25, sr)
    noisy = (speech + noise).astype("float32")

    cleaned = denoise_samples(noisy, sr, strength=0.95, stationary=True)

    # noise-only band (2-7 kHz) energy must drop substantially
    def hf_energy(x):
        spec = np.abs(np.fft.rfft(x))
        freqs = np.fft.rfftfreq(len(x), 1 / sr)
        band = (freqs > 2000) & (freqs < 7000)
        return float(np.mean(spec[band] ** 2))

    assert hf_energy(cleaned) < hf_energy(noisy) * 0.5


def test_denoise_preserves_voice_band():
    sr = 16000
    t = np.arange(sr) / sr
    voice = 0.4 * np.sin(2 * np.pi * 180 * t)
    cleaned = denoise_samples(voice.astype("float32"), sr, strength=0.85, stationary=True)
    # a clean tone must remain intelligible (high correlation with the input)
    corr = float(np.corrcoef(voice[:8000], cleaned[:8000])[0, 1])
    assert corr > 0.7, corr


def test_denoise_handles_short_and_silent_input():
    sr = 16000
    short = np.array([0.1, -0.1, 0.2], dtype="float32")
    assert np.array_equal(denoise_samples(short, sr), short)
    silence = np.zeros(sr, dtype="float32")
    out = denoise_samples(silence, sr)
    assert np.all(np.isfinite(out)) and float(np.max(np.abs(out))) < 0.01
