"use client";

// Voice Studio (PRD §3.4.4): speed, pitch, emotion/style, effect presets with
// live preview spoken through the `speak` WS frame (no LLM round trip).

import * as React from "react";
import { Play } from "lucide-react";
import { toast } from "sonner";

import { ChatSocket } from "@/lib/ws-client";
import { useApp } from "@/lib/store";
import type { WsFrame } from "@/lib/types";
import { AudioStreamPlayer } from "@/lib/audio-engine";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";
import { LanguagePicker } from "@/components/chat/language-picker";
import { VoicePickerButton } from "@/components/chat/voice-picker";
import { PageContainer, PageHeader } from "@/components/page-container";

const EFFECTS = [
  { id: "clean", label: "Clean" },
  { id: "radio", label: "Radio" },
  { id: "hall", label: "Hall" },
];

const STYLES = ["neutral", "calm", "warm"];

export default function StudioPage() {
  const { languages } = useApp();
  const [voiceId, setVoiceId] = React.useState("");
  const [voiceName, setVoiceName] = React.useState("Voice");
  const [lang, setLang] = React.useState("en");
  const [sentence, setSentence] = React.useState("This is how your voice will sound.");
  const [speed, setSpeed] = React.useState(1);
  const [pitch, setPitch] = React.useState(0);
  const [style, setStyle] = React.useState("neutral");
  const [effect, setEffect] = React.useState("clean");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<{
    audioId: string;
    engine: string;
    fallback: boolean;
    chunks: { b64: string; sr: number }[];
  } | null>(null);

  const socketRef = React.useRef<ChatSocket | null>(null);
  const playerRef = React.useRef<AudioStreamPlayer | null>(null);
  const chunksRef = React.useRef<{ b64: string; sr: number }[]>([]);
  const audioIdRef = React.useRef<string>("");

  React.useEffect(() => {
    // A conversation socket is required for `speak`; create a lightweight one.
    // The endpoint validates the conversation belongs to us — use a throwaway id
    // only after a real conversation exists; otherwise speak needs conv context.
    return () => {
      socketRef.current?.close();
      playerRef.current?.stop();
    };
  }, []);

  const handleFrame = (frame: WsFrame) => {
    if (frame.type === "audio") {
      chunksRef.current.push({ b64: frame.b64, sr: frame.sr });
      playerRef.current?.playChunk(frame.b64, frame.sr);
    } else if (frame.type === "done" && frame.audio_id) {
      audioIdRef.current = frame.audio_id;
      setResult({
        audioId: frame.audio_id,
        engine: frame.engine ?? "",
        fallback: frame.fallback ?? false,
        chunks: [...chunksRef.current],
      });
      playerRef.current?.markComplete();
      setBusy(false);
      if (frame.fallback) {
        toast.info(`Spoken with ${frame.engine} (fallback)`);
      }
    } else if (frame.type === "error") {
      toast.error(frame.message);
      setBusy(false);
    }
  };

  const preview = async () => {
    if (!sentence.trim()) return;
    setBusy(true);
    chunksRef.current = [];
    audioIdRef.current = "";
    playerRef.current = new AudioStreamPlayer();
    playerRef.current.setSpeed(speed);
    // reuse the chat socket of a hidden conversation is complex; speak requires
    // an existing conversation id — the server accepts the frame on any chat ws.
    if (!socketRef.current) {
      toast.error("Open a chat first, then come back to the studio");
      setBusy(false);
      return;
    }
    socketRef.current.speak(sentence, {
      voiceId,
      lang,
      speed,
      style: style === "neutral" ? undefined : style,
      effect: effect === "clean" ? undefined : effect,
      pitchSemitones: pitch,
    });
  };

  // The studio needs its own socket bound to the latest conversation. We look it
  // up lazily from localStorage echo set by the chat page.
  React.useEffect(() => {
    try {
      const convId = localStorage.getItem("bohurupi.active-conv");
      if (!convId) return;
      socketRef.current?.close();
      const sock = new ChatSocket(convId, { onFrame: handleFrame });
      socketRef.current = sock;
      sock.connect();
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <PageContainer size="narrow">
      <PageHeader
        title="Voice Studio"
        description="Tune speed, pitch, emotion and effects. Preview instantly."
      />

      <Card className="bg-gradient-card mt-4">
        <CardHeader>
          <CardTitle className="text-base">Preview sentence</CardTitle>
          <CardDescription>
            Written in the language below — spoken with your current settings.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          <div className="flex flex-wrap items-center gap-2">
            <VoicePickerButton
              value={voiceId}
              voiceName={voiceName}
              onChange={(v) => {
                setVoiceId(v.id);
                setVoiceName(v.name);
                // speak the first supported language of this voice
                if (v.languages.length > 0 && !v.languages.includes(lang)) {
                  setLang(v.languages[0]);
                }
              }}
            />
            <LanguagePicker value={lang} onChange={setLang} />
          </div>

          <Field>
            <FieldLabel htmlFor="sentence">Sentence</FieldLabel>
            <Input
              id="sentence"
              value={sentence}
              onChange={(e) => setSentence(e.target.value)}
            />
            <FieldDescription>
              {languages.find((l) => l.code === lang)?.native} ·{" "}
              {languages.find((l) => l.code === lang)?.name}
            </FieldDescription>
          </Field>

          <div className="grid gap-5 sm:grid-cols-2">
            <Field>
              <FieldLabel className="flex items-center justify-between">
                Speed <span className="tabular-nums text-muted-foreground">{speed.toFixed(2)}x</span>
              </FieldLabel>
              <Slider
                value={[speed]}
                min={0.5}
                max={2}
                step={0.05}
                onValueChange={(v) => setSpeed(Array.isArray(v) ? v[0] : v)}
                aria-label="Speed"
              />
            </Field>
            <Field>
              <FieldLabel className="flex items-center justify-between">
                Pitch{" "}
                <span className="tabular-nums text-muted-foreground">
                  {pitch > 0 ? `+${pitch.toFixed(1)}` : pitch.toFixed(1)} st
                </span>
              </FieldLabel>
              <Slider
                value={[pitch]}
                min={-6}
                max={6}
                step={0.5}
                onValueChange={(v) => setPitch(Array.isArray(v) ? v[0] : v)}
                aria-label="Pitch"
              />
            </Field>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <Field>
              <FieldLabel>Emotion / style</FieldLabel>
              <Select value={style} onValueChange={(v) => v && setStyle(v)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STYLES.map((s) => (
                    <SelectItem key={s} value={s} className="capitalize">
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel>Effect</FieldLabel>
              <Select value={effect} onValueChange={(v) => v && setEffect(v)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EFFECTS.map((e) => (
                    <SelectItem key={e.id} value={e.id}>
                      {e.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </div>

          <div className="flex items-center gap-3">
            <Button onClick={() => void preview()} disabled={busy}>
              {busy ? <Spinner data-icon="inline-start" /> : <Play data-icon="inline-start" />}
              Preview
            </Button>
            {result && (
              <>
                <Badge variant={result.fallback ? "destructive" : "secondary"}>
                  {result.fallback ? `${result.engine} (fallback)` : result.engine}
                </Badge>
                {result.audioId && (
                  <audio
                    controls
                    src={`${
                      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
                    }/audio/${result.audioId}`}
                    className="h-8"
                  />
                )}
              </>
            )}
          </div>
        </CardContent>
      </Card>

      <p className="mt-4 text-xs text-muted-foreground">
        Tip: the studio speaks through your latest chat conversation’s connection. Open the chat
        once after signing in, then return here.
      </p>
    </PageContainer>
  );
}
