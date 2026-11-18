// Shared types for the Bohurupi web client.

export interface Language {
  code: string;
  name: string;
  native: string;
  rtl: boolean;
}

export interface Voice {
  id: string;
  name: string;
  engine: string;
  languages: string[];
  gender: string | null;
  styles: string[];
  clonable: boolean;
  is_preset: boolean;
  status: string;
  owner_id: string | null;
}

export interface AudioAsset {
  id: string;
  message_id: string | null;
  voice_id: string;
  lang: string;
  engine: string;
  duration: number;
  sample_rate: number;
  watermark_id: string | null;
  created_at?: string;
}

export interface Conversation {
  id: string;
  title: string;
  default_lang: string;
  default_voice_id: string;
  updated_at: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  lang: string;
  translations?: Record<string, string> | null;
  created_at: string;
  audio?: AudioAsset[];
  // client-side streaming state
  streaming?: boolean;
  spokenWith?: string; // engine that spoke
  fallback?: boolean;
  // client-side audio chunks for the waveform
  pcm?: { b64: string; sr: number }[];
}

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  plan: string;
  created_at: string;
}

export interface UserSettings {
  theme: string;
  default_lang: string;
  default_voice_id: string;
  speed: number;
  auto_play: boolean;
  captions: boolean;
  engine_pref: string;
}

export interface Tokens {
  access_token: string;
  refresh_token: string;
  user: User;
}

// ---- WebSocket frames (mirror of the API contract) ----

export type WsFrame =
  | { type: "ready"; conversation_id: string }
  | { type: "status"; stage: string }
  | { type: "text_token"; v: string }
  | {
      type: "sentence_start";
      text: string;
      lang: string;
      engine: string;
      voice_id: string;
      fallback: boolean;
    }
  | { type: "audio"; seq: number; sr: number; b64: string }
  | { type: "sentence_end"; engine: string; voice_id?: string; fallback?: boolean }
  | { type: "sentence_error"; message: string }
  | {
      type: "done";
      message_id: string;
      user_message_id?: string;
      audio_id?: string;
      lang: string;
      text: string;
      voice_id?: string;
      engine?: string;
      fallback?: boolean;
      duration?: number;
      latency_ms?: number;
    }
  | { type: "error"; message: string }
  | { type: "pong" };

export interface EngineStatus {
  name: string;
  healthy: boolean;
  enabled: boolean;
  quality_rank: number;
  languages: string[];
}
