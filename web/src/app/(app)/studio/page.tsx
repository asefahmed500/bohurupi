"use client";

// Voice Studio (PRD §3.4.4): speed, pitch, emotion/style, effect presets with
// live preview spoken through the `speak` WS frame (no LLM round trip).
// Self-contained: it ensures a conversation exists instead of requiring the
// user to open chat first.

import * as React from "react";
import { toast } from "sonner";

import { speakPreview, audioObjectUrl, type SpeakResult } from "@/lib/speak";
import { AudioStreamPlayer } from "@/lib/audio-engine";
import { useApp } from "@/lib/store";
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
  const [result, setResult] = React.useState<(SpeakResult & { url?: string }) | null>(null);

  const playerRef = React.useRef<AudioStreamPlayer | null>(null);

  React.useEffect(() => {
    return () => {
      playerRef.current?.stop();
    };
  }, []);

  const preview = async () => {
    if (!sentence.trim() || busy) return;
    setBusy(true);
    setResult(null);
    playerRef.current?.stop();
    try {
      const res = await speakPreview({
        text: sentence.trim(),
        voiceId,
        lang,
        speed,
        style: style === "neutral" ? undefined : style,
        effect: effect === "clean" ? undefined : effect,
        pitchSemitones: pitch,
        onChunk: (p, b64, sr) => {
          playerRef.current = p; // the playing player comes from speak.ts
          p.playChunk(b64, sr);
        },
      });
      playerRef.current?.markComplete();
      let url: string | undefined;
      try {
        url = await audioObjectUrl(res.audioId);
      } catch {
        url = undefined;
      }
      setResult({ ...res, url });
      if (res.fallback) {
        toast.info(`Spoken with ${res.engine} (fallback)`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  };

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
                <SelectTrigger aria-label="Emotion / style">
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
                <SelectTrigger aria-label="Effect">
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

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => void preview()} loading={busy} disabled={!sentence.trim()}>
              Preview
            </Button>
            {result && (
              <>
                <Badge variant={result.fallback ? "destructive" : "secondary"}>
                  {result.fallback ? `${result.engine} (fallback)` : result.engine}
                </Badge>
                {result.url && (
                  <audio controls src={result.url} className="h-8" />
                )}
              </>
            )}
          </div>
        </CardContent>
      </Card>
    </PageContainer>
  );
}
