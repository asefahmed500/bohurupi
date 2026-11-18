"use client";

// WebSocket client for /ws/chat/{conv_id} with typed frames.

import { API_URL, loadTokens } from "./api";
import type { WsFrame } from "./types";

export interface ChatSocketHandlers {
  onFrame: (frame: WsFrame) => void;
  onClose?: (clean: boolean) => void;
  onOpen?: () => void;
}

export class ChatSocket {
  private ws: WebSocket | null = null;
  private handlers: ChatSocketHandlers;
  private closedByUser = false;

  constructor(
    private conversationId: string,
    handlers: ChatSocketHandlers
  ) {
    this.handlers = handlers;
  }

  connect() {
    const tokens = loadTokens();
    if (!tokens) return;
    const base = API_URL.replace(/^http/, "ws");
    this.closedByUser = false;
    this.ws = new WebSocket(
      `${base}/ws/chat/${this.conversationId}?token=${tokens.access_token}`
    );
    this.ws.onopen = () => this.handlers.onOpen?.();
    this.ws.onmessage = (event) => {
      try {
        const frame = JSON.parse(event.data as string) as WsFrame;
        this.handlers.onFrame(frame);
      } catch {
        // ignore malformed frames
      }
    };
    this.ws.onclose = (event) => {
      if (!this.closedByUser) this.handlers.onClose?.(event.code === 1000);
    };
  }

  send(frame: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(frame));
    }
  }

  chat(text: string, opts: { outLang?: string; voiceId?: string; speed?: number } = {}) {
    this.send({
      type: "chat",
      text,
      out_lang: opts.outLang ?? "auto",
      voice_id: opts.voiceId ?? "",
      speed: opts.speed ?? 1,
    });
  }

  respeak(
    messageId: string,
    opts: { voiceId: string; lang?: string; speed?: number }
  ) {
    this.send({
      type: "respeak",
      message_id: messageId,
      voice_id: opts.voiceId,
      lang: opts.lang ?? "",
      speed: opts.speed ?? 1,
    });
  }

  speak(
    text: string,
    opts: {
      voiceId?: string;
      lang?: string;
      speed?: number;
      style?: string;
      effect?: string;
      pitchSemitones?: number;
    } = {}
  ) {
    this.send({
      type: "speak",
      text,
      voice_id: opts.voiceId ?? "",
      lang: opts.lang ?? "en",
      speed: opts.speed ?? 1,
      style: opts.style,
      effect: opts.effect,
      pitch_semitones: opts.pitchSemitones ?? 0,
    });
  }

  ping() {
    this.send({ type: "ping" });
  }

  close() {
    this.closedByUser = true;
    this.ws?.close(1000);
    this.ws = null;
  }
}
