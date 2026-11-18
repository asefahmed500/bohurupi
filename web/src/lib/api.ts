"use client";

// REST client: base URL, auth headers, transparent refresh-on-401.

import type {
  AudioAsset,
  ChatMessage,
  Conversation,
  EngineStatus,
  Language,
  Tokens,
  User,
  UserSettings,
  Voice,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const AUTH_KEY = "bohurupi.auth";

export function loadTokens(): Tokens | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

export function saveTokens(tokens: Tokens | null) {
  if (typeof window === "undefined") return;
  if (tokens) localStorage.setItem(AUTH_KEY, JSON.stringify(tokens));
  else localStorage.removeItem(AUTH_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      const tokens = loadTokens();
      if (!tokens?.refresh_token) return false;
      const res = await fetch(`${API_URL}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      });
      if (!res.ok) return false;
      const next = (await res.json()) as Tokens;
      saveTokens({ ...next, refresh_token: next.refresh_token || tokens.refresh_token });
      return true;
    })().finally(() => {
      setTimeout(() => (refreshing = null), 0);
    });
  }
  return refreshing;
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<T> {
  const tokens = loadTokens();
  const headers = new Headers(options.headers);
  if (tokens) headers.set("Authorization", `Bearer ${tokens.access_token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (res.status === 401 && retry && tokens) {
    if (await tryRefresh()) {
      return api<T>(path, options, false);
    }
    saveTokens(null);
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      message = typeof body.detail === "string" ? body.detail : message;
    } catch {
      /* keep default */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- auth ----

export function register(email: string, password: string, name: string) {
  return api<Tokens>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, name }),
  });
}

export function login(email: string, password: string) {
  return api<Tokens>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export const getMe = () => api<User>("/auth/me");
export const getSettings = () => api<UserSettings>("/auth/settings");
export const putSettings = (patch: Partial<UserSettings>) =>
  api<UserSettings>("/auth/settings", { method: "PUT", body: JSON.stringify(patch) });

// ---- meta ----

export const getLanguages = () => api<{ languages: Language[] }>("/languages");
export const getHealth = () =>
  api<{ ok: boolean; llm: boolean; stt: boolean; engines: EngineStatus[] }>("/health");

// ---- conversations ----

export const listConversations = () =>
  api<{ conversations: Conversation[] }>("/conversations");

export function createConversation(body: Partial<Conversation> = {}) {
  return api<Conversation>("/conversations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getConversation(id: string) {
  const data = await api<{ conversation: Conversation; messages: ChatMessage[] }>(
    `/conversations/${id}`
  );
  return data;
}

export function patchConversation(id: string, body: Partial<Conversation>) {
  return api<Conversation>(`/conversations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export const deleteConversation = (id: string) =>
  api<void>(`/conversations/${id}`, { method: "DELETE" });

// ---- voices ----

export interface VoiceFilter {
  lang?: string;
  gender?: string;
  style?: string;
  q?: string;
  mine?: boolean;
}

export function listVoices(filter: VoiceFilter = {}) {
  const params = new URLSearchParams();
  if (filter.lang) params.set("lang", filter.lang);
  if (filter.gender) params.set("gender", filter.gender);
  if (filter.style) params.set("style", filter.style);
  if (filter.q) params.set("q", filter.q);
  if (filter.mine) params.set("mine", "true");
  const qs = params.toString();
  return api<{ voices: Voice[] }>(`/voices${qs ? `?${qs}` : ""}`);
}

export const deleteVoice = (id: string) => api<void>(`/voices/${id}`, { method: "DELETE" });

export const getConsentPhrase = (lang: string) =>
  api<{ phrase: string; lang: string }>(`/voices/consent-phrase?lang=${lang}`);

export function cloneVoice(
  fields: Record<string, string>,
  sample: File,
  consentAudio: File
) {
  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));
  form.append("sample", sample);
  form.append("consent_audio", consentAudio);
  return api<{ voice: Voice; status: string; note: string }>("/voices/clone", {
    method: "POST",
    body: form,
  });
}

// ---- audio ----

export const audioUrl = (id: string) => `${API_URL}/audio/${id}`;

export async function fetchAudioPcm(id: string): Promise<{ pcm: Float32Array; sr: number }> {
  const tokens = loadTokens();
  const res = await fetch(audioUrl(id), {
    headers: tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {},
  });
  if (!res.ok) throw new ApiError(res.status, "Could not load audio");
  const buf = await res.arrayBuffer();
  const ctx = new AudioContext();
  const decoded = await ctx.decodeAudioData(buf);
  await ctx.close();
  return { pcm: decoded.getChannelData(0), sr: decoded.sampleRate };
}

export async function downloadAudio(id: string, name: string) {
  const tokens = loadTokens();
  const res = await fetch(audioUrl(id), {
    headers: tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {},
  });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name || "bohurupi"}-${id.slice(0, 8)}.wav`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---- stt ----

export async function transcribe(file: Blob, language?: string) {
  const form = new FormData();
  form.append("file", file, "speech.webm");
  if (language) form.append("language", language);
  const tokens = loadTokens();
  const res = await fetch(`${API_URL}/stt`, {
    method: "POST",
    body: form,
    headers: tokens ? { Authorization: `Bearer ${tokens.access_token}` } : {},
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new ApiError(res.status, detail?.detail ?? "Speech recognition failed");
  }
  return (await res.json()) as { text: string; language: string; confidence: number };
}

// ---- admin ----

export const adminEngines = () => api<{ engines: EngineStatus[] }>("/admin/engines");
export const adminSetEngine = (name: string, enabled: boolean) =>
  api(`/admin/engines/${name}`, { method: "POST", body: JSON.stringify({ enabled }) });
export const adminUsage = (days = 30) =>
  api<{
    totals: { chars: number; seconds: number; events: number };
    by_type: Record<string, { chars: number; seconds: number; count: number }>;
    by_day: Record<string, { chars: number; seconds: number; count: number }>;
  }>(`/admin/usage?days=${days}`);
export const adminStats = () =>
  api<{ users: number; conversations: number; messages: number }>("/admin/stats");
export const adminUsers = () =>
  api<{
    users: {
      id: string;
      email: string;
      name: string;
      role: string;
      plan: string;
      created_at: string;
    }[];
  }>("/admin/users");
export const adminPendingVoices = () => api<{ voices: Voice[] }>("/admin/voices/moderation");
export const adminModerate = (voiceId: string, decision: "approve" | "reject") =>
  api<Voice>(`/admin/voices/${voiceId}/moderate`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
