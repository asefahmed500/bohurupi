"use client";

// Chat view — full-bleed page (the shell provides the fixed-height flex context).
// Desktop (xl+): chat column + voice/style side panel.
// The conversations rail lives in the app-shell sidebar (see ConversationsGroup),
// NOT here — one sidebar system only.

import * as React from "react";
import { Plus, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { createConversation, getConversation, patchConversation } from "@/lib/api";
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
  const { settings, updateSettings } = useApp();
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

  // refs so the WS handler always sees current values without reconnects
  const activeConvRef = React.useRef<Conversation | null>(null);
  activeConvRef.current = activeConv;
  const respeakingIdRef = React.useRef<string | null>(null);
  respeakingIdRef.current = respeakingId;
  const outLangRef = React.useRef(outLang);
  outLangRef.current = outLang;
  const speedRef = React.useRef(speed);
  speedRef.current = speed;
  const autoPlayRef = React.useRef(settings.auto_play);
  autoPlayRef.current = settings.auto_play;

  // ---- WS frame handling ----
  const appendChunk = React.useCallback((b64: string, sr: number) => {
    setLive((prev) => {
      const next = { ...prev, chunks: [...prev.chunks, { b64, sr }] };
      if (!livePlayerRef.current) {
        const player = new AudioStreamPlayer();
        player.setSpeed(speedRef.current);
        player.onDone(() => {
          livePlayerRef.current = null;
        });
        livePlayerRef.current = player;
      }
      livePlayerRef.current?.playChunk(b64, sr);
      return next;
    });
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
          else setLive((p) => ({ ...p, chunks: [...p.chunks, { b64: frame.b64, sr: frame.sr }] }));
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
            // re-speak flow: reload messages to pick up the new audio asset
            setRespeakingId(null);
            const conv = activeConvRef.current;
            if (conv) {
              void getConversation(conv.id).then((data) => setMessages(data.messages));
            }
            toast.success(
              `Re-spoken${doneFrame.fallback ? ` with ${doneFrame.engine} (fallback)` : ""}`
            );
            return;
          }
          setLive(EMPTY_LIVE);
          if (doneFrame.message_id && doneFrame.text) {
            setMessages((prev) => [
              ...prev.filter((m) => !(m.id.startsWith("local-") && m.text === "")),
              {
                id: doneFrame.message_id,
                role: "assistant",
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
            ]);
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
  handleFrameRef.current = handleFrame;

  const connectSocket = React.useCallback((convId: string) => {
    if (socketRef.current) {
      if (socketRef.current.targetId === convId) return; // already bound
      socketRef.current.close();
    }
    const sock = new ChatSocket(convId, {
      onFrame: (f) => handleFrameRef.current(f),
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
    setLive(EMPTY_LIVE);
    setRespeakingId(null);

    if (!activeId) {
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
      setMessages((prev) => [
        ...prev,
        {
          id: `local-${Date.now()}`,
          role: "user",
          text,
          lang: "",
          created_at: new Date().toISOString(),
        },
      ]);
      setLive({ streaming: true, text: "", chunks: [], stage: "thinking" });
      connectSocket(conv.id);
      // give the socket a tick to open if it was just created
      await new Promise((r) => setTimeout(r, 120));
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
      if (!sock) {
        toast.error("Chat is still connecting — try again in a second");
        return;
      }
      setRespeakingId(messageId);
      sock.respeak(messageId, {
        voiceId: v.id,
        lang: outLangRef.current === "auto" ? "" : outLangRef.current,
        speed: speedRef.current,
      });
    },
    []
  );

  const newConversation = () => setActiveId(null);

  const currentVoiceName = voice?.name ?? "Voice";

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
              <Button variant="outline" size="sm" className="rounded-full">
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
                            className="rounded-full"
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
                        onRespeak={
                          m.role === "assistant" ? (v) => respeak(m.id, v) : undefined
                        }
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
