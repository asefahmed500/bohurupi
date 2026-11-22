"use client";

// Chat view — full-bleed page (the shell provides the fixed-height flex context).
// Desktop (xl+): chat column + voice/style side panel.
// The conversations rail lives in the app-shell sidebar (see ConversationsGroup),
// NOT here — one sidebar system only.

import * as React from "react";
import { Plus, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { createConversation, getConversation, listVoices, patchConversation } from "@/lib/api";
import { useApp } from "@/lib/store";
import { useConversations } from "@/lib/conversations";
import { AudioStreamPlayer } from "@/lib/audio-engine";
import { ChatSocket } from "@/lib/ws-client";
import type { ChatMessage, Conversation, Voice, WsFrame } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Composer } from "./composer";
import { LanguagePicker } from "./language-picker";
import { MessageRow } from "./message-row";
import { VoicePickerButton } from "./voice-picker";

const STARTERS = [
  "Explain photosynthesis like I'm ten",
  "আমাকে আজকের খবরের সারসংক্ষেপ দাও",
  "Write a short birthday wish in Arabic",
];

interface LiveState {
  streaming: boolean;
  text: string;
  chunks: { b64: string; sr: number }[];
  engine?: string;
  fallback?: boolean;
  stage?: string;
}

const EMPTY_LIVE: LiveState = { streaming: false, text: "", chunks: [] };

export function ChatView() {
  const { settings, updateSettings, ready } = useApp();
  const { activeId, setActiveId, refresh, upsert } = useConversations();

  const [activeConv, setActiveConv] = React.useState<Conversation | null>(null);
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [live, setLive] = React.useState<LiveState>(EMPTY_LIVE);
  const [outLang, setOutLang] = React.useState(settings.default_lang);
  const [voice, setVoice] = React.useState<Voice | null>(null);
  const [speed, setSpeed] = React.useState(settings.speed);
  const [voiceToVoice, setVoiceToVoice] = React.useState(false);
  const [respeakingId, setRespeakingId] = React.useState<string | null>(null);

  const socketRef = React.useRef<ChatSocket | null>(null);
  const livePlayerRef = React.useRef<AudioStreamPlayer | null>(null);
  /** id of the optimistic local user message awaiting its server id */
  const pendingLocalIdRef = React.useRef<string | null>(null);

  // refs so the WS handler always sees current values without reconnects —
  // kept in sync after render (effects) so handlers only read committed state
  const activeConvRef = React.useRef<Conversation | null>(null);
  const respeakingIdRef = React.useRef<string | null>(null);
  const outLangRef = React.useRef(outLang);
  const speedRef = React.useRef(speed);
  const autoPlayRef = React.useRef(settings.auto_play);
  React.useEffect(() => {
    activeConvRef.current = activeConv;
    respeakingIdRef.current = respeakingId;
    outLangRef.current = outLang;
    speedRef.current = speed;
    autoPlayRef.current = settings.auto_play;
  }, [activeConv, respeakingId, outLang, speed, settings.auto_play]);

  // ---- WS frame handling ----
  // Player side effects stay OUTSIDE state updaters (updaters must be pure —
  // React may replay them, which would double-schedule audio).
  const appendChunk = React.useCallback((b64: string, sr: number) => {
    if (!livePlayerRef.current) {
      const player = new AudioStreamPlayer();
      player.setSpeed(speedRef.current);
      player.onDone(() => {
        livePlayerRef.current = null;
      });
      livePlayerRef.current = player;
    }
    livePlayerRef.current?.playChunk(b64, sr);
  }, []);

  const handleFrame = React.useCallback(
    (frame: WsFrame) => {
      switch (frame.type) {
        case "status":
          setLive((p) => ({ ...p, streaming: true, stage: frame.stage }));
          break;
        case "text_token":
          setLive((p) => ({ ...p, streaming: true, text: p.text + frame.v }));
          break;
        case "sentence_start":
          setLive((p) => ({
            ...p,
            streaming: true,
            engine: frame.engine,
            fallback: frame.fallback,
          }));
          break;
        case "audio":
          if (autoPlayRef.current) appendChunk(frame.b64, frame.sr);
          setLive((p) => ({ ...p, chunks: [...p.chunks, { b64: frame.b64, sr: frame.sr }] }));
          break;
        case "sentence_error":
          toast.warning(frame.message);
          break;
        case "error":
          toast.error(frame.message);
          setLive(EMPTY_LIVE);
          break;
        case "done": {
          const doneFrame = frame;
          livePlayerRef.current?.markComplete();
          if (respeakingIdRef.current) {
            // re-speak flow: splice the new audio asset into the existing
            // message instead of reloading the whole conversation (no flicker)
            const respeakTargetId = respeakingIdRef.current;
            setRespeakingId(null);
            if (doneFrame.audio_id) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === respeakTargetId
                    ? {
                        ...m,
                        audio: [
                          ...(m.audio ?? []),
                          {
                            id: doneFrame.audio_id!,
                            message_id: m.id,
                            voice_id: doneFrame.voice_id ?? "",
                            lang: doneFrame.lang,
                            engine: doneFrame.engine ?? "",
                            duration: doneFrame.duration ?? 0,
                            sample_rate: 24000,
                            watermark_id: null,
                          },
                        ],
                      }
                    : m
                )
              );
            }
            toast.success(
              `Re-spoken${doneFrame.fallback ? ` with ${doneFrame.engine} (fallback)` : ""}`
            );
            return;
          }
          setLive(EMPTY_LIVE);
          if (doneFrame.message_id && doneFrame.text) {
            setMessages((prev) => {
              // swap the optimistic local user message for the persisted one
              const next = prev.map((m) =>
                m.id === pendingLocalIdRef.current && doneFrame.user_message_id
                  ? { ...m, id: doneFrame.user_message_id }
                  : m
              );
              pendingLocalIdRef.current = null;
              return [
                ...next,
                {
                  id: doneFrame.message_id,
                  role: "assistant" as const,
                  text: doneFrame.text,
                  lang: doneFrame.lang,
                  created_at: new Date().toISOString(),
                  audio: doneFrame.audio_id
                    ? [
                        {
                          id: doneFrame.audio_id,
                          message_id: doneFrame.message_id,
                          voice_id: doneFrame.voice_id ?? "",
                          lang: doneFrame.lang,
                          engine: doneFrame.engine ?? "",
                          duration: doneFrame.duration ?? 0,
                          sample_rate: 24000,
                          watermark_id: null,
                        },
                      ]
                    : undefined,
                  spokenWith: doneFrame.engine,
                  fallback: doneFrame.fallback,
                },
              ];
            });
          }
          void refresh();
          return;
        }
        default:
          break;
      }
    },
    [appendChunk, refresh]
  );

  const handleFrameRef = React.useRef(handleFrame);
  React.useEffect(() => {
    handleFrameRef.current = handleFrame;
  }, [handleFrame]);

  const connectSocket = React.useCallback((convId: string) => {
    const current = socketRef.current;
    if (current && current.targetId === convId) {
      const state = current.readyState();
      if (state === "open" || state === "connecting") return; // healthy, already bound
      // dead socket (server restart, network drop) — replace it
      current.close();
      socketRef.current = null;
    }
    const sock = new ChatSocket(convId, {
      onFrame: (f) => handleFrameRef.current(f),
      onClose: () => {
        // drop the dead socket so the next send reconnects
        if (socketRef.current === sock) socketRef.current = null;
      },
    });
    sock.targetId = convId;
    socketRef.current = sock;
    sock.connect();
  }, []);

  // ---- load conversation on activeId change (sidebar is the source of truth) ----
  React.useEffect(() => {
    // fresh-create path: send() already bound this conversation and socket —
    // re-running the full load here would wipe the optimistic message and
    // open a second socket (the double-connect bug).
    if (activeConvRef.current?.id === activeId) return;

    socketRef.current?.close();
    socketRef.current = null;
    livePlayerRef.current?.stop();
    livePlayerRef.current = null;
    // intentional state reset when switching conversations
    setLive(EMPTY_LIVE);
    setRespeakingId(null);

    if (!activeId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional reset on "new conversation"
      setActiveConv(null);
      setMessages([]);
      localStorage.removeItem("bohurupi.active-conv");
      return;
    }
    localStorage.setItem("bohurupi.active-conv", activeId);
    let cancelled = false;
    void (async () => {
      try {
        const data = await getConversation(activeId);
        if (cancelled) return;
        setActiveConv(data.conversation);
        setMessages(data.messages);
        if (data.conversation.default_lang && data.conversation.default_lang !== "auto") {
          setOutLang(data.conversation.default_lang);
        }
        connectSocket(activeId);
      } catch {
        if (!cancelled) toast.error("Could not open this conversation");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId, connectSocket]);

  // ---- initial selection: most recent conversation ----
  const bootstrapped = React.useRef(false);
  React.useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    void (async () => {
      const convs = await refresh();
      if (convs.length > 0) setActiveId(convs[0].id);
    })();
  }, [refresh, setActiveId]);

  // ---- actions ----
  const send = React.useCallback(
    async (text: string) => {
      let conv = activeConvRef.current;
      if (!conv) {
        try {
          conv = await createConversation({ default_lang: outLang });
          setActiveConv(conv);
          upsert(conv); // show in the sidebar immediately
          setActiveId(conv.id); // highlight; the load effect skips (same conversation)
          localStorage.setItem("bohurupi.active-conv", conv.id);
        } catch {
          toast.error("Could not start a conversation");
          return;
        }
      }
      const localId = `local-${Date.now()}`;
      pendingLocalIdRef.current = localId;
      setMessages((prev) => [
        ...prev,
        {
          id: localId,
          role: "user",
          text,
          lang: "",
          created_at: new Date().toISOString(),
        },
      ]);
      setLive({ streaming: true, text: "", chunks: [], stage: "thinking" });
      connectSocket(conv.id);
      // send immediately — the socket queues frames while connecting
      socketRef.current?.chat(text, {
        outLang,
        voiceId: voice?.id ?? "",
        speed,
      });
    },
    [connectSocket, outLang, setActiveId, speed, upsert, voice]
  );

  const respeak = React.useCallback(
    (messageId: string, v: Voice) => {
      const sock = socketRef.current;
      if (!sock || sock.readyState() === "closed" || sock.readyState() === "none") {
        if (activeConvRef.current) connectSocket(activeConvRef.current.id);
        toast.error("Reconnecting — try again in a second");
        return;
      }
      setRespeakingId(messageId);
      sock.respeak(messageId, {
        voiceId: v.id,
        lang: outLangRef.current === "auto" ? "" : outLangRef.current,
        speed: speedRef.current,
      });
    },
    [connectSocket]
  );

  const newConversation = () => setActiveId(null);

  const currentVoiceName = voice?.name ?? "Voice";

  // adopt saved defaults once user settings arrive (initial useState snapshot
  // happens before the async settings fetch completes)
  const defaultsAdopted = React.useRef(false);
  React.useEffect(() => {
    if (defaultsAdopted.current || !ready) return;
    defaultsAdopted.current = true;
    setOutLang(settings.default_lang);
    setSpeed(settings.speed);
  }, [ready, settings.default_lang, settings.speed]);

  // resolve the default voice's display name for the header button
  React.useEffect(() => {
    if (voice || !settings.default_voice_id) return;
    let cancelled = false;
    listVoices({})
      .then((res) => {
        if (cancelled) return;
        const match = res.voices.find((v) => v.id === settings.default_voice_id);
        if (match) setVoice(match);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [voice, settings.default_voice_id]);

  return (
    <div className="flex h-full min-h-0">
      {/* chat column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* page header (chat) */}
        <header className="flex items-center gap-2 border-b bg-card/60 px-3 py-2 backdrop-blur sm:px-4">
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="New conversation"
            onClick={newConversation}
          >
            <Plus />
          </Button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">
            {activeConv?.title ?? "New conversation"}
          </h1>
          <LanguagePicker
            value={outLang}
            onChange={(code) => {
              setOutLang(code);
              if (activeConv) {
                void patchConversation(activeConv.id, { default_lang: code });
              }
            }}
            trigger={
              <Button variant="outline" size="sm" className="rounded-md">
                <Sparkles data-icon="inline-start" />
                <span className="hidden sm:inline">
                  Reply in: {outLang === "auto" ? "Auto" : outLang}
                </span>
                <span className="sm:hidden">{outLang === "auto" ? "Auto" : outLang}</span>
              </Button>
            }
          />
          <VoicePickerButton
            value={voice?.id ?? settings.default_voice_id}
            voiceName={currentVoiceName}
            onChange={(v) => {
              setVoice(v);
              void updateSettings({ default_voice_id: v.id });
            }}
          />
        </header>

        {/* messages */}
        <MessageScrollerProvider>
          <div className="relative min-h-0 flex-1">
            <MessageScroller>
              <MessageScrollerViewport>
                <MessageScrollerContent className="mx-auto w-full max-w-3xl px-3 py-6 sm:px-4">
                  {messages.length === 0 && !live.streaming && (
                    <div className="flex flex-col items-center gap-6 py-16 text-center">
                      <div className="flex size-14 items-center justify-center rounded-2xl border bg-card">
                        <Sparkles className="size-6 text-muted-foreground" />
                      </div>
                      <div>
                        <h2 className="text-lg font-semibold">
                          Speak or type in any language
                        </h2>
                        <p className="mt-1 text-sm text-muted-foreground">
                          The reply is spoken in the language and voice you choose.
                        </p>
                      </div>
                      <div className="flex flex-col gap-2 sm:flex-row">
                        {STARTERS.map((s) => (
                          <Button
                            key={s}
                            variant="outline"
                            size="sm"
                            className="rounded-md"
                            onClick={() => void send(s)}
                          >
                            {s}
                          </Button>
                        ))}
                      </div>
                    </div>
                  )}

                  {messages.map((m) => (
                    <MessageScrollerItem key={m.id} scrollAnchor>
                      <MessageRow
                        message={m}
                        onRespeak={m.role === "assistant" ? respeak : undefined}
                        respeaking={respeakingId === m.id}
                      />
                    </MessageScrollerItem>
                  ))}

                  {live.streaming && (
                    <MessageScrollerItem scrollAnchor>
                      <MessageRow
                        message={{
                          id: "live",
                          role: "assistant",
                          text: live.text,
                          lang: "",
                          created_at: new Date().toISOString(),
                          pcm: live.chunks,
                        }}
                        generating
                        spokenWith={live.engine}
                        fallback={live.fallback}
                      />
                    </MessageScrollerItem>
                  )}
                </MessageScrollerContent>
              </MessageScrollerViewport>
              <MessageScrollerButton />
            </MessageScroller>
          </div>
        </MessageScrollerProvider>

        {/* composer (docks above the mobile tab bar via the shell height contract) */}
        <div className="border-t bg-card/60 px-3 pt-3 pb-3 backdrop-blur sm:px-4 md:pb-4">
          <div className="mx-auto w-full max-w-3xl">
            <Composer
              onSend={(t) => void send(t)}
              busy={live.streaming}
              voiceToVoice={voiceToVoice}
            />
            <div className="mt-2 flex items-center justify-center gap-4 text-xs text-muted-foreground md:justify-start">
              <label className="flex items-center gap-1.5">
                <Switch
                  checked={voiceToVoice}
                  onCheckedChange={setVoiceToVoice}
                  aria-label="Voice-to-voice mode"
                />
                Voice-to-voice
              </label>
              <span className="hidden sm:inline">
                Enter to send · Shift+Enter for newline
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* voice & style panel (xl+) — part of the chat page, not the shell */}
      <aside className="hidden w-72 shrink-0 flex-col gap-4 overflow-y-auto border-l bg-card/50 p-4 xl:flex">
        <div>
          <h2 className="text-sm font-semibold">Voice & style</h2>
          <p className="text-xs text-muted-foreground">Applies to the next reply.</p>
        </div>
        <Separator />
        <div className="flex flex-col gap-3">
          <Label className="text-xs text-muted-foreground">Voice</Label>
          <VoicePickerButton
            value={voice?.id ?? settings.default_voice_id}
            voiceName={currentVoiceName}
            onChange={(v) => {
              setVoice(v);
              void updateSettings({ default_voice_id: v.id });
            }}
          />
        </div>
        <div className="flex flex-col gap-3">
          <Label className="flex items-center justify-between text-xs text-muted-foreground">
            Speed <span className="tabular-nums">{speed.toFixed(2)}x</span>
          </Label>
          <Slider
            value={[speed]}
            min={0.5}
            max={2}
            step={0.05}
            onValueChange={(v) => setSpeed(Array.isArray(v) ? v[0] : v)}
            aria-label="Speech speed"
          />
        </div>
        <Separator />
        <div className="flex items-center justify-between">
          <Label htmlFor="autoplay" className="text-xs text-muted-foreground">
            Auto-play replies
          </Label>
          <Switch
            id="autoplay"
            checked={settings.auto_play}
            onCheckedChange={(v) => void updateSettings({ auto_play: v })}
          />
        </div>
        <div className="flex items-center justify-between">
          <Label htmlFor="captions" className="text-xs text-muted-foreground">
            Captions
          </Label>
          <Switch
            id="captions"
            checked={settings.captions}
            onCheckedChange={(v) => void updateSettings({ captions: v })}
          />
        </div>
        <Separator />
        <p className="text-xs leading-relaxed text-muted-foreground">
          Tip: open any reply and use “Change voice” to re-speak it in another voice or language —
          the answer isn’t regenerated.
        </p>
      </aside>
    </div>
  );
}
