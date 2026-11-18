"use client";

// AudioBar: waveform (canvas), play/pause, speed, download.
// Streams live chunks during generation; plays stored WAVs for history.

import * as React from "react";
import { ArrowDownToLine, Pause, Play } from "lucide-react";
import { toast } from "sonner";

import { downloadAudio, fetchAudioPcm } from "@/lib/api";
import { AudioStreamPlayer, b64ChunksToPeaks, computePeaks } from "@/lib/audio-engine";
import type { AudioAsset } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";

const SPEEDS = ["0.75", "1", "1.25", "1.5"];

export function AudioBar({
  asset,
  chunks,
  generating,
}: {
  asset?: AudioAsset;
  chunks?: { b64: string; sr: number }[];
  generating?: boolean;
}) {
  const playerRef = React.useRef<AudioStreamPlayer | null>(null);
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const [playing, setPlaying] = React.useState(false);
  const [speed, setSpeed] = React.useState("1");
  const [peaks, setPeaks] = React.useState<number[]>([]);
  const [position, setPosition] = React.useState(0);
  const [loading, setLoading] = React.useState(false);

  const duration = asset?.duration ?? (chunks?.length ? chunks.length * 0.2 : 0);

  // derive peaks
  React.useEffect(() => {
    let cancelled = false;
    if (chunks && chunks.length > 0) {
      setPeaks(b64ChunksToPeaks(chunks));
      return;
    }
    if (asset) {
      setLoading(true);
      fetchAudioPcm(asset.id)
        .then(({ pcm }) => {
          if (!cancelled) setPeaks(computePeaks(pcm));
        })
        .catch(() => {
          if (!cancelled) setPeaks([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [asset?.id, chunks]);

  // draw waveform
  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const list = peaks.length ? peaks : Array.from({ length: 56 }, () => 0.12);
    const progress = duration > 0 ? Math.min(1, position / duration) : 0;
    const barW = Math.max(2, w / list.length - 2);
    const gap = Math.min(3, Math.max(1, w / list.length - barW));
    list.forEach((p, i) => {
      const x = i * (barW + gap);
      const barH = Math.max(2, p * (h - 6));
      const y = (h - barH) / 2;
      const played = i / list.length <= progress;
      ctx.fillStyle = played ? "oklch(0.227 0 0)" : "oklch(0.75 0.006 106)";
      ctx.beginPath();
      ctx.roundRect(x, y, barW, barH, barW / 2);
      ctx.fill();
    });
  }, [peaks, position, duration]);

  // progress ticker while playing
  React.useEffect(() => {
    if (!playing) return;
    const t = window.setInterval(() => {
      setPosition(playerRef.current?.position() ?? 0);
    }, 120);
    return () => window.clearInterval(t);
  }, [playing]);

  const stop = React.useCallback(() => {
    playerRef.current?.stop();
    setPlaying(false);
    setPosition(0);
  }, []);

  const toggle = async () => {
    if (playing) {
      stop();
      return;
    }
    if (chunks && chunks.length > 0) {
      // live-streamed playback from WS frames
      const player = new AudioStreamPlayer();
      playerRef.current = player;
      player.setSpeed(Number(speed));
      player.onDone(() => {
        setPlaying(false);
        setPosition(0);
      });
      for (const c of chunks) player.playChunk(c.b64, c.sr);
      player.markComplete();
      setPlaying(true);
      return;
    }
    if (asset) {
      setLoading(true);
      try {
        const { pcm, sr } = await fetchAudioPcm(asset.id);
        const player = new AudioStreamPlayer();
        playerRef.current = player;
        player.setSpeed(Number(speed));
        player.onDone(() => {
          setPlaying(false);
          setPosition(0);
        });
        player.playBuffer(pcm, sr);
        setPlaying(true);
      } catch {
        toast.error("Could not play this audio");
      } finally {
        setLoading(false);
      }
    }
  };

  // stop on unmount
  React.useEffect(() => stop, [stop]);

  return (
    <div className="flex items-center gap-2 rounded-full border bg-card py-1.5 pr-2 pl-1.5">
      <Button
        size="icon-sm"
        onClick={toggle}
        disabled={generating || (!chunks?.length && !asset)}
        aria-label={playing ? "Pause" : "Play"}
        className="rounded-full"
      >
        {loading || generating ? (
          <Spinner className="size-4" />
        ) : playing ? (
          <Pause />
        ) : (
          <Play />
        )}
      </Button>
      <canvas
        ref={canvasRef}
        className="h-7 min-w-24 flex-1"
        style={{ width: "160px" }}
        aria-hidden
      />
      <Select
        value={speed}
        onValueChange={(v) => {
          if (!v) return;
          setSpeed(v);
          playerRef.current?.setSpeed(Number(v));
        }}
      >
        <SelectTrigger
          size="sm"
          className="w-16 rounded-full border-none shadow-none"
          aria-label="Playback speed"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {SPEEDS.map((s) => (
            <SelectItem key={s} value={s}>
              {s}x
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {asset && (
        <Button
          size="icon-sm"
          variant="ghost"
          className="rounded-full"
          aria-label="Download audio"
          onClick={() => downloadAudio(asset.id, "bohurupi").catch(() => toast.error("Download failed"))}
        >
          <ArrowDownToLine />
        </Button>
      )}
    </div>
  );
}
