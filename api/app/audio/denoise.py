"""Free, open-source noise suppression for speech recognition.

Primary: `noisereduce` (MIT) spectral gating — stationary (noise profile from
the first quiet segment) or non-stationary (crowded / changing background).
Fallback: a self-contained numpy spectral gate with the same idea, used if the
optional dependency is missing so STT never hard-fails because of it.

All processing is local: no external audio service, no data leaves the device.
"""

import logging

import numpy as np

logger = logging.getLogger("bohurupi.denoise")


def _highpass(x: np.ndarray, sr: int, cutoff_hz: float = 80.0) -> np.ndarray:
    """First-order RC high-pass — removes rumble, HVAC and handling noise."""
    if len(x) < 2:
        return x
    try:
        from scipy.signal import butter, sosfiltfilt

        sos = butter(2, cutoff_hz, btype="highpass", fs=sr, output="sos")
        return sosfiltfilt(sos, x).astype(np.float32)
    except ImportError:
        pass  # small numpy fallback below
    dt = 1.0 / sr
    rc = 1.0 / (2 * np.pi * cutoff_hz)
    alpha = rc / (rc + dt)
    out = np.empty_like(x)
    out[0] = x[0]
    prev_x, prev_y = x[0], x[0]
    for i in range(1, len(x)):
        prev_y = alpha * (prev_y + x[i] - prev_x)
        out[i] = prev_y
        prev_x = x[i]
    return out


def _numpy_gate(x: np.ndarray, sr: int, strength: float) -> np.ndarray:
    """Spectral gate fallback: noise floor from the quietest 10% of frames."""
    n_fft = 512
    hop = n_fft // 4
    if len(x) < n_fft * 2:
        return x
    pad = n_fft - (len(x) - n_fft) % hop
    padded = np.pad(x, (0, pad))
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop]
    spec = np.fft.rfft(frames * np.hanning(n_fft), axis=1)
    mag = np.abs(spec)
    floor = np.quantile(mag, 0.1, axis=0)
    # soft gate: 0 for noise-only bins, 1 for clearly above the floor
    mask = np.clip((mag - floor * 1.4) / (floor * 1.4 + 1e-8), 0.0, 1.0)
    mask = 1.0 - strength + strength * mask
    cleaned = np.fft.irfft(spec * mask, n=n_fft, axis=1)

    out = np.zeros(len(padded), dtype=np.float64)
    weight = np.zeros(len(padded), dtype=np.float64)
    window = np.hanning(n_fft)
    for i, frame in enumerate(cleaned):
        start = i * hop
        out[start : start + n_fft] += frame * window
        weight[start : start + n_fft] += window
    nonzero = weight > 1e-8
    out[nonzero] /= weight[nonzero]
    return out[: len(x)].astype(np.float32)


def denoise_samples(
    mono: np.ndarray,
    sr: int,
    *,
    strength: float = 0.85,
    stationary: bool = False,
) -> np.ndarray:
    """Return a denoised mono float32 signal.

    `stationary=True` estimates the noise profile from the first 0.3 s (good for
    constant fan/traffic noise); False tracks a changing floor (crowded rooms).
    """
    x = np.asarray(mono, dtype=np.float32).reshape(-1)
    if len(x) < sr // 10 or not np.any(np.isfinite(x)):  # too short / invalid
        return np.nan_to_num(x)
    x = np.nan_to_num(x)
    if float(np.max(np.abs(x))) < 1e-9:  # digital silence: don't let the gate divide by zero
        return x.copy()
    x = _highpass(x, sr)
    strength = float(np.clip(strength, 0.0, 1.0))
    try:
        import noisereduce as nr

        kwargs = {
            "y": x,
            "sr": int(sr),
            "stationary": bool(stationary),
            "prop_decrease": strength,
            "n_fft": 512,  # Context7: recommended for speech
            "time_constant_s": 1.2,
        }
        if stationary:
            kwargs["y_noise"] = x[: min(len(x), int(0.3 * sr))]
        out = np.asarray(nr.reduce_noise(**kwargs), dtype=np.float32).reshape(-1)
    except Exception:
        logger.warning("noisereduce unavailable — using numpy spectral gate")
        out = _numpy_gate(x, sr, strength)
    # guard against NaN/Inf produced by the gate on very quiet or silent audio
    out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    # gentle level normalization so distant speech is still audible to Whisper
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 1e-6:
        target = min(1.0, max(0.25, peak))
        out = out * (target / peak)
    return out.astype(np.float32)
