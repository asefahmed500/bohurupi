"use client";

// Shared TTS preview: ensures a conversation exists, opens a chat socket,
// streams the `speak` frame and resolves with the rendered audio.

import { API_URL, createConversation, listConversations } from "@/lib/api";
import { AudioStreamPlayer } from "@/lib/audio-engine";
import { ChatSocket } from "@/lib/ws-client";
import type { WsFrame } from "@/lib/types";

export interface SpeakResult {
  audioId: string;
  engine: string;
  fallback: boolean;
  duration: number;
  chunks: { b64: string; sr: number }[];
}

export interface SpeakOptions {
  text: string;
  voiceId?: string;
  lang?: string;
  speed?: number;
  style?: string;
  effect?: string;
  pitchSemitones?: number;
  /** called for every audio chunk as it streams in (e.g. to play live) */
  onChunk?: (player: AudioStreamPlayer, b64: string, sr: number) => void;
  signal?: AbortSignal;
}

/** Resolve a conversation id for previews — dedicated "Voice preview"
 * conversation so previews never pollute the user's real chat thread. */
export async function ensureConversationId(): Promise<string> {
  try {
    const res = await listConversations();
    const existing = res.conversations.find((c) => c.title === "Voice preview");
    if (existing) return existing.id;
  } catch {
    /* fall through to create */
  }
  const conv = await createConversation({ title: "Voice preview" });
  return conv.id;
}

export async function speakPreview(opts: SpeakOptions): Promise<SpeakResult> {
  const convId = await ensureConversationId();
  return new Promise<SpeakResult>((resolve, reject) => {
    const chunks: { b64: string; sr: number }[] = [];
    const player = new AudioStreamPlayer();
    let settled = false;

    const sock = new ChatSocket(convId, {
      onFrame: (frame: WsFrame) => {
        if (settled) return;
        if (frame.type === "ready") {
          sock.speak(opts.text, {
            voiceId: opts.voiceId,
            lang: opts.lang,
            speed: opts.speed,
            style: opts.style,
            effect: opts.effect,
            pitchSemitones: opts.pitchSemitones,
          });
        } else if (frame.type === "audio") {
          chunks.push({ b64: frame.b64, sr: frame.sr });
          opts.onChunk?.(player, frame.b64, frame.sr);
        } else if (frame.type === "done") {
          settled = true;
          player.markComplete();
          sock.close();
          if (frame.type === "done" && frame.audio_id) {
            resolve({
              audioId: frame.audio_id,
              engine: frame.engine ?? "",
              fallback: frame.fallback ?? false,
              duration: frame.duration ?? 0,
              chunks,
            });
          } else {
            reject(new Error("No audio produced"));
          }
        } else if (frame.type === "error") {
          settled = true;
          sock.close();
          reject(new Error(frame.message));
        }
      },
      onClose: () => {
        if (!settled) {
          settled = true;
          reject(new Error("Connection closed before audio finished"));
        }
      },
    });

    if (opts.signal) {
      opts.signal.addEventListener("abort", () => {
        if (!settled) {
          settled = true;
          sock.close();
          player.stop();
          reject(new Error("Cancelled"));
        }
      });
    }

    sock.connect();
  });
}

/** Fetch an authenticated audio asset as an object URL for <audio> elements. */
export async function audioObjectUrl(id: string): Promise<string> {
  const { loadTokens } = await import("@/lib/api");
  const tokens = loadTokens();
  const res = await fetch(`${API_URL}/audio/${id}`, {
    headers: tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {},
  });
  if (!res.ok) throw new Error("Could not load audio");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}
