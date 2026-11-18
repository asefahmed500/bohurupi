"""Direct engine smoke test: kokoro + edge synthesis to WAV files."""

import asyncio
import sys

sys.path.insert(0, ".")

from app.engines.edge import EdgeEngine
from app.engines.kokoro import KokoroEngine
from app.services.storage import pcm_to_wav_bytes, root


async def synth(engine, text, lang, voice_id, out_name):
    chunks = []
    try:
        async for c in engine.synthesize(text, lang, voice_id):
            chunks.append(c)
    except Exception as e:
        print(f"[FAIL] {engine.name}: {e}")
        return False
    if not chunks:
        print(f"[FAIL] {engine.name}: no audio")
        return False
    pcm = b"".join(c.pcm for c in chunks)
    sr = chunks[0].sample_rate
    data = pcm_to_wav_bytes(pcm, sr)
    out = root() / out_name
    out.write_bytes(data)
    dur = len(pcm) / 2 / sr
    print(f"[OK] {engine.name}: {dur:.2f}s @ {sr}Hz -> {out} ({len(data)} bytes)")
    return True


async def main():
    print("1) Kokoro (English)...")
    koko = KokoroEngine()
    await koko.warmup()
    ok1 = await synth(
        koko,
        "Hello from Bohurupi, your multilingual voice agent.",
        "en",
        "kokoro:af-heart",
        "test_kokoro_en.wav",
    )

    print("2) Edge (Bangla)...")
    edge = EdgeEngine()
    ok2 = await synth(
        edge,
        "বহুরূপী একটি বহুভাষিক ভয়েস এজেন্ট।",
        "bn",
        "edge:bd-nabanita-f",
        "test_edge_bn.wav",
    )

    print(f"\nRESULT: kokoro={ok1} edge={ok2}")


asyncio.run(main())
