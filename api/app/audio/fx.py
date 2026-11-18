"""Audio effects via pedalboard (Voice Studio presets). Optional dependency:
returns input untouched when pedalboard is not installed."""

import logging

logger = logging.getLogger("bohurupi.fx")

PRESETS = {
    "clean": [],
    "radio": ["highpass", "lowpass", "compressor", "gain"],
    "hall": ["reverb", "gain"],
}


def is_available() -> bool:
    try:
        import pedalboard  # noqa: F401

        return True
    except ImportError:
        return False


def apply_effect(pcm: bytes, sample_rate: int, preset: str | None) -> bytes:
    """Apply an effect preset to mono int16 PCM. Passthrough on missing preset/deps."""
    if not preset or preset == "clean" or preset not in PRESETS:
        return pcm
    try:
        import numpy as np
        import pedalboard as pb
        from pedalboard import Compressor, Gain, HighpassFilter, LowpassFilter, Reverb
    except ImportError:
        logger.info("pedalboard not installed; skipping effect '%s'", preset)
        return pcm

    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    chain: list = []
    if preset == "radio":
        chain = [
            HighpassFilter(cutoff_frequency_hz=300.0),
            LowpassFilter(cutoff_frequency_hz=3400.0),
            Compressor(threshold_db=-18, ratio=3.5, attack_ms=5, release_ms=80),
            Gain(gain_db=1.5),
        ]
    elif preset == "hall":
        chain = [
            Reverb(room_size=0.75, damping=0.4, wet_level=0.28, dry_level=0.75),
            Gain(gain_db=0.5),
        ]
    board = pb.Pedalboard(chain)
    out = board(x, sample_rate)
    return (np.clip(out, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def pitch_shift(pcm: bytes, sample_rate: int, semitones: float) -> bytes:
    """Cheap pitch shift via resampling (preserves tempo poorly; fine for preview)."""
    if abs(semitones) < 0.01:
        return pcm
    try:
        import numpy as np
    except ImportError:
        return pcm
    x = np.frombuffer(pcm, dtype="<i2")
    n = int(len(x) * (2 ** (-semitones / 12)))
    idx = np.linspace(0, len(x) - 1, n)
    x2 = np.interp(idx, np.arange(len(x)), x.astype(np.float64))
    return np.clip(x2, -32768, 32767).astype("<i2").tobytes()
