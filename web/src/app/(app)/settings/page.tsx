"use client";

// Settings (PRD §3.4.6): theme, defaults, playback, engine preference, privacy.

import * as React from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";

import { deleteVoice, listVoices } from "@/lib/api";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { VoicePickerButton } from "@/components/chat/voice-picker";
import { LanguagePicker } from "@/components/chat/language-picker";

export default function SettingsPage() {
  const { settings, updateSettings, user } = useApp();
  const [myVoices, setMyVoices] = React.useState<{ id: string; name: string }[]>([]);

  React.useEffect(() => {
    if (!user) return;
    listVoices({ mine: true })
      .then((res) => setMyVoices(res.voices.map((v) => ({ id: v.id, name: v.name }))))
      .catch(() => undefined);
  }, [user]);

  const removeVoice = async (id: string, name: string) => {
    if (!confirm(`Delete "${name}"? The voice sample and embeddings are removed permanently.`))
      return;
    try {
      await deleteVoice(id);
      setMyVoices((prev) => prev.filter((v) => v.id !== id));
      toast.success("Voice deleted permanently");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <div className="mx-auto w-full max-w-2xl p-4 sm:p-6">
      <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
      <p className="text-sm text-muted-foreground">Theme, defaults, playback and privacy.</p>

      <div className="mt-4 flex flex-col gap-4">
        <Card className="bg-gradient-card">
          <CardHeader>
            <CardTitle className="text-base">Appearance</CardTitle>
          </CardHeader>
          <CardContent>
            <Field>
              <FieldLabel>Theme</FieldLabel>
              <Select
                value={settings.theme}
                onValueChange={(v) => v && void updateSettings({ theme: v })}
              >
                <SelectTrigger className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="system">System</SelectItem>
                  <SelectItem value="light">Light</SelectItem>
                  <SelectItem value="dark">Dark</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </CardContent>
        </Card>

        <Card className="bg-gradient-card">
          <CardHeader>
            <CardTitle className="text-base">Defaults</CardTitle>
            <CardDescription>Used for every new conversation.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex flex-col gap-1.5">
                <FieldLabel className="text-xs text-muted-foreground">Language</FieldLabel>
                <LanguagePicker
                  value={settings.default_lang}
                  onChange={(code) => void updateSettings({ default_lang: code })}
                  trigger={
                    <Button variant="outline" size="sm">
                      {settings.default_lang === "auto" ? "Auto" : settings.default_lang}
                    </Button>
                  }
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <FieldLabel className="text-xs text-muted-foreground">Voice</FieldLabel>
                <VoicePickerButton
                  value={settings.default_voice_id}
                  voiceName={settings.default_voice_id || "Voice"}
                  onChange={(v) => void updateSettings({ default_voice_id: v.id })}
                />
              </div>
            </div>
            <Field>
              <FieldLabel className="flex items-center justify-between">
                Default speed{" "}
                <span className="tabular-nums text-muted-foreground">
                  {settings.speed.toFixed(2)}x
                </span>
              </FieldLabel>
              <Slider
                value={[settings.speed]}
                min={0.5}
                max={2}
                step={0.05}
                onValueChange={(v) => void updateSettings({ speed: Array.isArray(v) ? v[0] : v })}
                aria-label="Default speed"
              />
            </Field>
            <Field>
              <FieldLabel>Engine preference</FieldLabel>
              <Select
                value={settings.engine_pref}
                onValueChange={(v) => v && void updateSettings({ engine_pref: v })}
              >
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="quality">Quality — best voice first</SelectItem>
                  <SelectItem value="fast">Fast — lowest latency</SelectItem>
                  <SelectItem value="coverage">Coverage — any language</SelectItem>
                </SelectContent>
              </Select>
              <FieldDescription>
                If the preferred engine cannot speak a language, Bohurupi automatically falls
                back and tells you which voice was used.
              </FieldDescription>
            </Field>
          </CardContent>
        </Card>

        <Card className="bg-gradient-card">
          <CardHeader>
            <CardTitle className="text-base">Playback & accessibility</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <div>
                <FieldLabel>Auto-play replies</FieldLabel>
                <FieldDescription>Speak answers as soon as the first sentence is ready.</FieldDescription>
              </div>
              <Switch
                checked={settings.auto_play}
                onCheckedChange={(v) => void updateSettings({ auto_play: v })}
                aria-label="Auto-play replies"
              />
            </div>
            <Separator />
            <div className="flex items-center justify-between">
              <div>
                <FieldLabel>Captions</FieldLabel>
                <FieldDescription>Always show text alongside audio.</FieldDescription>
              </div>
              <Switch
                checked={settings.captions}
                onCheckedChange={(v) => void updateSettings({ captions: v })}
                aria-label="Captions"
              />
            </div>
            <Separator />
            <p className="text-xs text-muted-foreground">
              Keyboard: <kbd className="rounded border bg-muted px-1">Space</kbd> play/pause ·{" "}
              <kbd className="rounded border bg-muted px-1">M</kbd> microphone. Reduced-motion is
              respected automatically.
            </p>
          </CardContent>
        </Card>

        <Card className="bg-gradient-card">
          <CardHeader>
            <CardTitle className="text-base">Data & privacy</CardTitle>
            <CardDescription>
              Your plan: <span className="capitalize">{user?.plan}</span>
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {myVoices.length === 0 ? (
              <p className="text-sm text-muted-foreground">No cloned voices.</p>
            ) : (
              myVoices.map((v) => (
                <div key={v.id} className="flex items-center gap-2 rounded-lg border p-3">
                  <span className="min-w-0 flex-1 truncate text-sm">{v.name}</span>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void removeVoice(v.id, v.name)}
                  >
                    <Trash2 data-icon="inline-start" />
                    Delete
                  </Button>
                </div>
              ))
            )}
            <p className="text-xs text-muted-foreground">
              Deleting a voice removes its sample, consent audio and embeddings permanently.
              Voice samples are encrypted at rest.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
