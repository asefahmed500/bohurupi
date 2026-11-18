"""Inaudible audio watermarking via audioseal (FR-7, PRD §2.11).

Optional dependency: when audioseal/torch are absent, generation embeds a
metadata-only mark (watermark_id stored on the asset) and detection reports
unavailable. Install the `fx` extra for real watermarking.
"""

import logging
import uuid

logger = logging.getLogger("bohurupi.watermark")

_model = None


def is_available() -> bool:
    try:
        import audioseal  # noqa: F401

        return True
    except ImportError:
        return False


def new_watermark_id() -> str:
    return "wm_" + uuid.uuid4().hex[:16]


def watermark(pcm: bytes, sample_rate: int) -> tuple[bytes, str]:
    """Apply watermark to mono int16 PCM. Returns (pcm, watermark_id)."""
    wm_id = new_watermark_id()
    if not is_available():
        return pcm, wm_id  # metadata-only mark
    try:
        global _model
        import numpy as np
        import torch
        from audioseal import AudioSeal

        if _model is None:
            _model = AudioSeal.load_generator("audioseal_wm_16bits")

        x = torch.from_numpy(
            np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        )[None, None, :]
        watermarked = _model(x, sample_rate=sample_rate)[0, 0].detach().numpy()
        return (np.clip(watermarked, -1.0, 1.0) * 32767.0).astype("<i2").tobytes(), wm_id
    except Exception as e:
        logger.warning("Watermarking failed (%s); storing metadata mark only", e)
        return pcm, wm_id


def detect(pcm: bytes, sample_rate: int) -> dict:
    """Detect a watermark. Returns {'watermarked': bool, 'confidence': float}."""
    if not is_available():
        return {"watermarked": False, "confidence": 0.0, "available": False}
    try:
        import numpy as np
        import torch
        from audioseal import AudioSeal

        detector = AudioSeal.load_detector("audioseal_detector_16bits")
        x = torch.from_numpy(
            np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        )[None, None, :]
        result, message = detector(x, sample_rate=sample_rate)
        frac = float((message[0] >= 0).float().mean().item())
        return {
            "watermarked": bool(result.mean().item() > 0.5),
            "confidence": result.mean().item(),
            "bits_match": frac,
            "available": True,
        }
    except Exception as e:
        logger.warning("Watermark detection failed: %s", e)
        return {"watermarked": False, "confidence": 0.0, "available": False}
