"use client";

// Chat view — conversations rail, message stream, composer.
// Desktop: conversations live in the sidebar; xl adds a voice/style panel.
// Phone: single column, mic docked above the composer (PRD §3.3).

import * as React from "react";
import { Plus, Sparkles } from "lucide-react";
import { toast } from "sonner";

import {
  createConversation,
  getConversation,
  listConversations,
  patchConversation,
} from "@/lib/api";
import { useApp } from "@/lib/store";
import { ChatSocket } from "@/lib/ws-client";
import type { ChatMessage, Conversation, Voice } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { AudioStreamPlayer } from "@/lib/audio-engine";
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

export function ChatView() {
  const { settings, user, updateSettings } = useApp();
  const [conversations, setConversations] = React.useState<Conversation[]>([]);
  const [active, setActive] = React.useState<Conversation | null>(null);
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [live, setLive] = React.useState<LiveState>({
    streaming: false,
    text: "",
    chunks: [],
  });
  const [outLang, setOutLang] = React.useState(settings.default_lang);
  const [voice, setVoice] = React.useState<Voice | null>(null);
  const [speed, setSpeed] = React.useState(settings.speed);
  const [voiceToVoice, setVoiceToVoice] = React.useState(false);
  const [respeakingId, setRespeakingId] = React.useState<string | null>(null);

  const socketRef = React.useRef<ChatSocket | null>(null);
  const livePlayerRef = React.useRef<AudioStreamPlayer | null>(null);
  // refs so the WS handler always sees current values without reconnects
  const activeRef = React.useRef<Conversation | null>(null);
  activeRef.current = active;
  const respeakingIdRef = React.useRef<string | null>(null);
  respeakingIdRef.current = respeakingId;

  // ---- data load ----
  const refreshConversations = React.useCallback(async () => {
    try {
      const res = await listConversations();
      setConversations(res.conversations);
      return res.conversations;
    } catch {
      return [];
    }
  }, []);

  const openConversation = React.useCallback(async (conv: Conversation) => {
    setActive(conv);
    setLive({ streaming: false, text: "", chunks: [] });
    socketRef.current?.close();
    localStorage.setItem("bohurupi.active-conv", conv.id);
    try {
      const data = await getConversation(conv.id);
      setMessages(data.messages.map((m) => ({ ...m, streaming: false })));
      const sock = new ChatSocket(conv.id, {
        onFrame: (f) => handleFrame(f),
      });
      socketRef.current = sock;
      sock.connect();
    } catch {
      toast.error("Could not open this conversation");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    void (async () => {
      const convs = await refreshConversations();
      if (convs.length > 0) void openConversation(convs[0]);
    })();
    return () => socketRef.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- WS frame handling ----
  const appendChunk = React.useCallback((b64: string, sr: number) => {
    setLive((prev) => {
      const next = { ...prev, chunks: [...prev.chunks, { b64, sr }] };
      if (!livePlayerRef.current) {
        livePlayerRef.current = new AudioStreamPlayer();
        const player = livePlayerRef.current;
        player.setSpeed(speed);
        player.onDone(() => {
          livePlayerRef.current = null;
        });
      }
      livePlayerRef.current.playChunk(b64, sr);
      return next;
    });
  }, [speed]);

  const handleFrame = React.useCallback(
    (frame: import("@/lib/types").WsFrame) => {
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
          if (settings.auto_play) appendChunk(frame.b64, frame.sr);
          else setLive((p) => ({ ...p, chunks: [...p.chunks, { b64: frame.b64, sr: frame.sr }] }));
          break;
        case "sentence_error":
          toast.warning(frame.message);
          break;
        case "error":
          toast.error(frame.message);
          setLive({ streaming: false, text: "", chunks: [] });
          break;
        case "done": {
          // commit the live bubble into history
          const doneFrame = frame;
          livePlayerRef.current?.markComplete();
          if (respeakingIdRef.current) {
            // respeak flow: reload messages to pick up the new audio asset
            setRespeakingId(null);
            if (activeRef.current) {
              void getConversation(activeRef.current.id).then((data) =>
                setMessages(data.messages)
              );
            }
            toast.success(`Re-spoken${doneFrame.fallback ? ` with ${doneFrame.engine} (fallback)` : ""}`);
            return;
          }
          setLive({ streaming: false, text: "", chunks: [] });
          if (doneFrame.message_id) {
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
          livePlayerRef.current?.markComplete();
          void refreshConversations();
          return;
        }
        default:
          break;
      }
    },
    [appendChunk, refreshConversations, settings.auto_play]
  );

  // remove the empty placeholder user bubble when done lands (text arrives via conversation reload)
  // — assistant bubble carries the reply; user text comes from `messages` after reload. To keep
  // it simple we re-fetch the conversation after each done frame:


  // ---- actions ----
  const send = React.useCallback(
    async (text: string) => {
      let conv = active;
      if (!conv) {
        try {
          conv = await createConversation({ default_lang: outLang });
          setActive(conv);
          localStorage.setItem("bohurupi.active-conv", conv.id);
        } catch {
          toast.error("Could not start a conversation");
          return;
        }
      }
      // optimistic user bubble
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
      if (!socketRef.current) {
        const sock = new ChatSocket(conv.id, { onFrame: handleFrame });
        socketRef.current = sock;
        sock.connect();
        // small delay to let ws accept
        await new Promise((r) => setTimeout(r, 150));
      }
      socketRef.current?.chat(text, { outLang, voiceId: voice?.id ?? "", speed });
    },
    [active, outLang, voice, speed, handleFrame]
  );

  const newConversation = async () => {
    socketRef.current?.close();
    socketRef.current = null;
    setActive(null);
    setMessages([]);
    setLive({ streaming: false, text: "", chunks: [] });
    localStorage.removeItem("bohurupi.active-conv");
  };

  const outLangRef = React.useRef(outLang);
  outLangRef.current = outLang;
  const speedRef = React.useRef(speed);
  speedRef.current = speed;
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

  const currentVoiceName = voice?.name ?? "Voice";

  return (
    <div className="flex h-dvh min-h-dvh">
      {/* conversations rail (md+) */}
      <Sidebar collapsible="none" className="hidden lg:flex">
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel className="justify-between">
              Conversations
              <Button
                size="icon-xs"
                variant="ghost"
                aria-label="New conversation"
                onClick={newConversation}
              >
                <Plus />
              </Button>
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {conversations.slice(0, 30).map((c) => (
                  <SidebarMenuItem key={c.id}>
                    <SidebarMenuButton
                      isActive={active?.id === c.id}
                      onClick={() => void openConversation(c)}
                    >
                      <span className="truncate">{c.title}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
                {conversations.length === 0 && (
                  <p className="px-2 py-1 text-xs text-muted-foreground">No conversations yet</p>
                )}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarRail />
      </Sidebar>

      {/* chat column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* header */}
        <header className="flex items-center gap-2 border-b bg-card/60 px-3 py-2 backdrop-blur sm:px-4">
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="New conversation"
            onClick={newConversation}
            className="lg:hidden"
          >
            <Plus />
          </Button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">
            {active?.title ?? "New conversation"}
          </h1>
          <LanguagePicker
            value={outLang}
            onChange={(code) => {
              setOutLang(code);
              if (active) void patchConversation(active.id, { default_lang: code });
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
                        <h2 className="text-lg font-semibold">Speak or type in any language</h2>
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
                        onRespeak={m.role === "assistant" ? (v) => respeak(m.id, v) : undefined}
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

        {/* composer */}
        <div className="border-t bg-card/60 px-3 pt-3 pb-3 backdrop-blur sm:px-4 md:pb-4">
          <div className="mx-auto w-full max-w-3xl">
            <Composer onSend={(t) => void send(t)} busy={live.streaming} voiceToVoice={voiceToVoice} />
            <div className="mt-2 flex items-center justify-center gap-4 text-xs text-muted-foreground md:justify-start">
              <label className="flex items-center gap-1.5">
                <Switch checked={voiceToVoice} onCheckedChange={setVoiceToVoice} aria-label="Voice-to-voice mode" />
                Voice-to-voice
              </label>
              <span className="hidden sm:inline">Enter to send · Shift+Enter for newline · M to mic</span>
            </div>
          </div>
        </div>
      </div>

      {/* voice & style panel (xl+) */}
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
          Tip: open any reply and use “Change voice” to re-speak it in another
          voice or language — the answer isn’t regenerated.
        </p>
      </aside>
    </div>
  );
}
