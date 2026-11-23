"""Live A/B: STT accuracy on crowd-noise speech, denoise OFF vs ON.

Clean speech comes from the free Edge TTS engine; crowd noise is synthesized
locally (white hiss + overlapping modulated voices + low rumble). Both audio
variants are sent to the real /stt endpoint and word error rate is measured.
"""

import asyncio
import io
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_tts
import httpx
import numpy as np
import soundfile as sf

BASE = "http://localhost:8000"
TEXT = "The quick brown fox jumps over the lazy dog. Please call customer support tomorrow morning."


def wav_bytes(mono: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, mono.astype("float32"), sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def wer(reference: str, hypothesis: str) -> float:
    a = reference.lower().replace(".", "").replace(",", "").split()
    b = hypothesis.lower().replace(".", "").replace(",", "").split()
    if not a:
        return 0.0 if not b else 1.0
    # Levenshtein distance
    dp = list(range(len(b) + 1))
    for i, word in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, other in enumerate(b, 1):
            old = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (word != other))
            prev = old
    return dp[-1] / len(a)


async def main() -> None:
    print("[setup] generating clean speech with edge-tts ...", flush=True)
    mp3 = bytearray()
    async for chunk in edge_tts.Communicate(TEXT, "en-US-AriaNeural").stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])
    mono, sr = sf.read(io.BytesIO(bytes(mp3)), dtype="float32")
    if mono.ndim > 1:
        mono = mono.mean(axis=1)
    # resample to 16k with simple linear interpolation for faster-whisper
    n = int(len(mono) * 16000 / sr)
    mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono).astype("float32")
    sr = 16000

    rng = np.random.default_rng(42)
    t = np.arange(len(mono)) / sr
    # crowd-like noise at a realistic ~8 dB SNR: hiss + modulated voices + rumble
    hiss = rng.normal(0, 0.08, len(mono))
    voice1 = 0.07 * np.sin(2 * np.pi * (150 + 12 * np.sin(2 * np.pi * 1.3 * t)) * t)
    voice2 = 0.06 * np.sin(2 * np.pi * (230 + 20 * np.sin(2 * np.pi * 0.9 * t)) * t)
    rumble = 0.06 * np.sin(2 * np.pi * 55 * t)
    slam = np.zeros(len(mono))
    slam[int(0.4 * sr) : int(0.55 * sr)] += 0.3 * np.hanning(int(0.15 * sr))
    noise = hiss + voice1 + voice2 + rumble + slam
    noisy = mono + noise
    peak = float(np.max(np.abs(noisy)))
    noisy = (noisy / peak * 0.95).astype("float32")

    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(
            f"{BASE}/auth/register",
            json={"email": f"denoise-{int(time.time())}@example.com", "password": "supersecret1"},
        )
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

        results = {}
        for flag in ("false", "true"):
            files = {"file": ("crowd.wav", wav_bytes(noisy, sr), "audio/wav")}
            res = await c.post(f"{BASE}/stt", headers=auth, data={"language": "en", "denoise": flag}, files=files)
            if res.status_code != 200:
                print(f"[FAIL] STT denoise={flag}: HTTP {res.status_code} {res.text[:150]}")
                return
            body = res.json()
            results[flag] = body
            print(f"[INFO] denoise={flag}: denoised={body['denoised']} text={body['text'][:130]!r}", flush=True)

    w_off = wer(TEXT, results["false"]["text"])
    w_on = wer(TEXT, results["true"]["text"])
    print(f"\nWER without denoising: {w_off:.3f}")
    print(f"WER with denoising:    {w_on:.3f}")
    if w_on <= w_off:
        print("\nNOISE SUPPRESSION: PASS (denoising improved or matched transcription)")
    else:
        print("\nNOISE SUPPRESSION: NEEDS TUNING (denoised WER worse)")
        raise SystemExit(1)


asyncio.run(main())
