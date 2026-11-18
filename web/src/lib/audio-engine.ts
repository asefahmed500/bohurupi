"use client";

// Web Audio streaming player: plays a queue of base64 PCM chunks (WS frames)
// or a full Float32 buffer, with speed control, pause/resume and position.

type DoneHandler = () => void;

interface QueuedSource {
  source: AudioBufferSourceNode;
  buffer: AudioBuffer;
  startAt: number; // ctx.currentTime when scheduled
  duration: number;
}

export class AudioStreamPlayer {
  private ctx: AudioContext | null = null;
  private gain: GainNode | null = null;
  private sources: QueuedSource[] = [];
  private scheduleHead = 0;
  private speed = 1;
  private startedAt = 0; // wall clock of first chunk (context time)
  private doneHandler: DoneHandler | null = null;
  private playing = false;
  private seenTotal = 0; // seconds of audio fed in
  private progressTimer: number | null = null;

  private ensureCtx() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.gain = this.ctx.createGain();
      this.gain.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") void this.ctx.resume();
    return this.ctx;
  }

  isPlaying() {
    return this.playing;
  }

  get totalSeconds() {
    return this.seenTotal;
  }

  /** Current playback position in seconds (for waveform progress). */
  position(): number {
    if (!this.ctx || !this.playing || this.sources.length === 0) return 0;
    const elapsed = (this.ctx.currentTime - this.startedAt) * this.speed;
    return Math.max(0, Math.min(elapsed, this.seenTotal));
  }

  onDone(handler: DoneHandler) {
    this.doneHandler = handler;
  }

  setSpeed(rate: number) {
    const clamped = Math.min(2, Math.max(0.5, rate));
    const ctx = this.ctx;
    if (!ctx) {
      this.speed = clamped;
      return;
    }
    // Re-anchor the timeline so progress stays consistent after the rate change.
    const pos = this.position();
    this.speed = clamped;
    if (this.playing) this.startedAt = ctx.currentTime - pos / clamped;
    for (const s of this.sources) {
      try {
        s.source.playbackRate.value = clamped;
      } catch {
        /* source may have ended */
      }
    }
  }

  /** Feed one streamed PCM chunk (base64 int16 mono). */
  playChunk(b64: string, sampleRate: number) {
    const ctx = this.ensureCtx();
    const bin = atob(b64);
    const len = bin.length >> 1;
    const pcm = new Float32Array(len);
    const view = new DataView(new ArrayBuffer(bin.length));
    for (let i = 0; i < bin.length; i++) {
      view.setUint8(i, bin.charCodeAt(i));
    }
    for (let i = 0; i < len; i++) {
      pcm[i] = view.getInt16(i * 2, true) / 32768;
    }

    const buffer = ctx.createBuffer(1, len, sampleRate);
    buffer.copyToChannel(pcm, 0);

    if (!this.playing) {
      this.playing = true;
      this.scheduleHead = ctx.currentTime + 0.05;
      this.startedAt = ctx.currentTime;
      this.sources = [];
    }

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.playbackRate.value = this.speed;
    src.connect(this.gain!);
    const duration = len / sampleRate;
    src.start(this.scheduleHead);
    this.scheduleHead += duration / this.speed;
    this.seenTotal += duration;

    const entry: QueuedSource = { source: src, buffer, startAt: this.scheduleHead, duration };
    src.onended = () => {
      this.sources = this.sources.filter((s) => s.source !== src);
      if (this.playing && this.sources.length === 0 && this.queueEmpty) {
        this.finish();
      }
    };
    this.sources.push(entry);
  }

  /** Signal that no more chunks are coming (finishes when buffer drains). */
  private queueEmpty = false;

  markComplete() {
    this.queueEmpty = true;
    if (this.playing && this.sources.length === 0) this.finish();
  }

  /** Play a full pre-rendered buffer (e.g. a stored WAV asset). */
  playBuffer(pcm: Float32Array, sampleRate: number) {
    this.stop();
    const ctx = this.ensureCtx();
    const buffer = ctx.createBuffer(1, pcm.length, sampleRate);
    buffer.copyToChannel(pcm as unknown as Float32Array<ArrayBuffer>, 0);
    this.playing = true;
    this.queueEmpty = true;
    this.seenTotal = pcm.length / sampleRate;
    this.startedAt = ctx.currentTime;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.playbackRate.value = this.speed;
    src.connect(this.gain!);
    src.start();
    this.sources = [{ source: src, buffer, startAt: ctx.currentTime, duration: this.seenTotal }];
    src.onended = () => {
      this.sources = this.sources.filter((s) => s.source !== src);
      this.finish();
    };
    this.startProgress();
  }

  pause() {
    this.ctx?.suspend();
  }

  resume() {
    void this.ctx?.resume();
  }

  isPaused() {
    return this.ctx?.state === "suspended";
  }

  stop() {
    for (const s of this.sources) {
      try {
        s.source.onended = null;
        s.source.stop();
      } catch {
        /* already stopped */
      }
    }
    this.sources = [];
    this.playing = false;
    this.queueEmpty = false;
    this.seenTotal = 0;
    this.stopProgress();
  }

  private finish() {
    this.playing = false;
    this.stopProgress();
    this.doneHandler?.();
  }

  private startProgress() {
    if (this.progressTimer != null) return;
    this.progressTimer = window.setInterval(() => {
      if (this.playing && this.sources.length === 0 && this.queueEmpty) this.finish();
    }, 250);
  }

  private stopProgress() {
    if (this.progressTimer != null) {
      clearInterval(this.progressTimer);
      this.progressTimer = null;
    }
  }
}

// ---- waveform helpers ----

export function computePeaks(pcm: Float32Array, buckets = 64): number[] {
  const peaks: number[] = [];
  const size = Math.max(1, Math.floor(pcm.length / buckets));
  for (let b = 0; b < buckets; b++) {
    let max = 0;
    const start = b * size;
    const end = Math.min(start + size, pcm.length);
    for (let i = start; i < end; i += 4) {
      const v = Math.abs(pcm[i]);
      if (v > max) max = v;
    }
    peaks.push(max);
  }
  const norm = Math.max(0.05, ...peaks);
  return peaks.map((p) => p / norm);
}

export function b64ChunksToPeaks(chunks: { b64: string; sr: number }[], buckets = 64): number[] {
  // approximate peaks from raw int16 bytes without full decode
  const peaks: number[] = [];
  let all: number[] = [];
  for (const c of chunks) {
    const bin = atob(c.b64);
    const stride = Math.max(2, Math.floor(bin.length / 400)) & ~1; // even stride
    for (let i = 0; i + 1 < bin.length; i += stride) {
      const v = Math.abs(((bin.charCodeAt(i) | (bin.charCodeAt(i + 1) << 8)) << 16) >> 16) / 32768;
      all.push(v);
    }
  }
  const size = Math.max(1, Math.floor(all.length / buckets));
  for (let b = 0; b < buckets; b++) {
    let max = 0;
    for (let i = b * size; i < Math.min((b + 1) * size, all.length); i++) {
      if (all[i] > max) max = all[i];
    }
    peaks.push(max);
  }
  const norm = Math.max(0.05, ...peaks);
  return peaks.map((p) => p / norm);
}
