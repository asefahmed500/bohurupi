"use client";

// Voice library: presets, my voices, cloned — search + filters + play (PRD §3.4.2).

import * as React from "react";
import Link from "next/link";
import { Heart, Mic, Play, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { deleteVoice, listVoices, trainVoice } from "@/lib/api";
import { speakPreview } from "@/lib/speak";
import { AudioStreamPlayer } from "@/lib/audio-engine";
import { useApp } from "@/lib/store";
import type { Voice } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageContainer, PageHeader } from "@/components/page-container";

// one-word greeting per launch language so the preview speaks the right script
const GREETINGS: Record<string, string> = {
  bn: "নমস্কার",
  en: "Hello",
  hi: "नमस्ते",
  ur: "ہیلو",
  ar: "مرحبا",
  es: "Hola",
  fr: "Bonjour",
  de: "Hallo",
  pt: "Olá",
  ru: "Привет",
  tr: "Merhaba",
  zh: "你好",
  ja: "こんにちは",
  ko: "안녕하세요",
  it: "Ciao",
  nl: "Hallo",
  pl: "Cześć",
  id: "Halo",
  ta: "வணக்கம்",
  vi: "Xin chào",
};

export default function VoicesPage() {
  const { user } = useApp();
  const [voices, setVoices] = React.useState<Voice[] | null>(null);
  const [tab, setTab] = React.useState<"presets" | "mine">("presets");
  const [query, setQuery] = React.useState("");
  const [lang, setLang] = React.useState("all");
  const [gender, setGender] = React.useState("all");
  const [previewingId, setPreviewingId] = React.useState<string | null>(null);
  const [trainingId, setTrainingId] = React.useState<string | null>(null);
  const [favoritesOnly, setFavoritesOnly] = React.useState(false);
  const [favorites, setFavorites] = React.useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("bohurupi.fav-voices") ?? "[]");
    } catch {
      return [];
    }
  });
  const { languages } = useApp();
  const previewPlayerRef = React.useRef<AudioStreamPlayer | null>(null);

  const load = React.useCallback(async () => {
    setVoices(null);
    try {
      const res = await listVoices({
        q: query || undefined,
        lang: lang === "all" ? undefined : lang,
        gender: gender === "all" ? undefined : gender,
        mine: tab === "mine",
      });
      setVoices(res.voices);
    } catch {
      setVoices([]);
    }
  }, [query, lang, gender, tab]);

  React.useEffect(() => {
    const t = setTimeout(() => void load(), 200);
    return () => clearTimeout(t);
  }, [load]);

  React.useEffect(() => () => previewPlayerRef.current?.stop(), []);

  const remove = async (id: string) => {
    if (
      !confirm("Delete this voice? The sample, consent audio and embeddings are removed permanently.")
    ) {
      return;
    }
    try {
      await deleteVoice(id);
      toast.success("Voice deleted");
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const preview = async (v: Voice) => {
    if (previewingId === v.id) {
      previewPlayerRef.current?.stop();
      previewPlayerRef.current = null;
      setPreviewingId(null);
      return;
    }
    previewPlayerRef.current?.stop();
    const voiceLang = v.languages[0] ?? "en";
    const greeting = GREETINGS[voiceLang] ?? "Hello";
    setPreviewingId(v.id);
    try {
      await speakPreview({
        text: `${greeting} — ${greeting}`,
        voiceId: v.id,
        lang: voiceLang,
        onChunk: (p, b64, sr) => {
          previewPlayerRef.current = p; // the playing player comes from speak.ts
          p.playChunk(b64, sr);
        },
      });
      // speak.ts marks the queue complete on done; if the clip already
      // finished while we awaited, clear the spinner right away
      const active = previewPlayerRef.current;
      if (active?.isPlaying()) {
        active.onDone(() => setPreviewingId((cur) => (cur === v.id ? null : cur)));
      } else {
        setPreviewingId(null);
      }
    } catch (e) {
      setPreviewingId(null);
      toast.error(e instanceof Error ? e.message : "Preview failed");
    }
  };

  const toggleFav = (id: string) => {
    setFavorites((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      localStorage.setItem("bohurupi.fav-voices", JSON.stringify(next));
      return next;
    });
  };

  const train = async (id: string) => {
    setTrainingId(id);
    try {
      const res = await trainVoice(id);
      toast.success(`Voice profile v${res.version} trained from your consented samples`);
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Training failed");
    } finally {
      setTrainingId(null);
    }
  };

  return (
    <PageContainer size="default">
      <PageHeader
        title="Voice library"
        description="Presets by language, gender and style — plus your own cloned voices."
        actions={
          <Link href="/voices/clone" className={buttonVariants()}>
            <Plus data-icon="inline-start" />
            Clone a voice
          </Link>
        }
      />

      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <Tabs value={tab} onValueChange={(v) => setTab(v as "presets" | "mine")}>
          <TabsList>
            <TabsTrigger value="presets">Presets</TabsTrigger>
            <TabsTrigger value="mine">My voices</TabsTrigger>
          </TabsList>
        </Tabs>
        <Button
          variant={favoritesOnly ? "secondary" : "outline"}
          size="sm"
          aria-pressed={favoritesOnly}
          onClick={() => setFavoritesOnly((v) => !v)}
        >
          <Heart data-icon="inline-start" className={favoritesOnly ? "fill-current" : undefined} />
          Favorites{favorites.length > 0 ? ` (${favorites.length})` : ""}
        </Button>
        <div className="relative flex-1">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search voices…"
            aria-label="Search voices"
          />
        </div>
        <div className="flex gap-2">
          <Select value={lang} onValueChange={(v) => v && setLang(v)}>
            <SelectTrigger className="w-36" aria-label="Language">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Any language</SelectItem>
              {languages.map((l) => (
                <SelectItem key={l.code} value={l.code}>
                  {l.native}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={gender} onValueChange={(v) => v && setGender(v)}>
            <SelectTrigger className="w-28" aria-label="Gender">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="female">Female</SelectItem>
              <SelectItem value="male">Male</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="mt-6">
        {(() => {
          if (voices === null) {
            return (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Array.from({ length: 9 }).map((_, i) => (
                  <Skeleton key={i} className="h-24 rounded-xl" />
                ))}
              </div>
            );
          }
          const visible = favoritesOnly
            ? voices.filter((v) => favorites.includes(v.id))
            : voices;
          if (visible.length === 0) {
            return (
              <Empty className="rounded-xl border bg-card">
                <EmptyHeader>
                  <EmptyMedia>
                    <Mic />
                  </EmptyMedia>
                  <EmptyTitle>
                    {favoritesOnly
                      ? "No favorites yet"
                      : tab === "mine"
                        ? "No voices yet"
                        : "No voices match"}
                  </EmptyTitle>
                  <EmptyDescription>
                    {favoritesOnly
                      ? "Tap the heart on a voice to save it here (stored on this device)."
                      : tab === "mine"
                        ? "Clone your own voice from a 10–30 second sample, or use presets."
                        : "Try different search or filters."}
                  </EmptyDescription>
                </EmptyHeader>
              </Empty>
            );
          }
          return (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {visible.map((v) => (
              <Card key={v.id} className="bg-gradient-card py-0">
                <CardContent className="flex h-full flex-col gap-2 p-4">
                  <div className="flex items-start gap-2">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary">
                      <Mic className="size-4 text-muted-foreground" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{v.name}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {v.engine} · {v.languages.slice(0, 4).join(", ")}
                        {v.languages.length > 4 ? ` +${v.languages.length - 4}` : ""}
                      </p>
                    </div>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={favorites.includes(v.id) ? "Unfavorite" : "Favorite"}
                      onClick={() => toggleFav(v.id)}
                    >
                      <Heart
                        className={favorites.includes(v.id) ? "fill-foreground" : undefined}
                      />
                    </Button>
                  </div>
                  <div className="mt-auto flex flex-wrap items-center gap-1.5">
                    {v.gender && <Badge variant="secondary">{v.gender}</Badge>}
                    {v.status !== "ready" && (
                      <Badge variant="outline" className="capitalize">
                        {v.status}
                      </Badge>
                    )}
                    {!v.is_preset && (
                      <Button
                        size="xs"
                        variant="outline"
                        loading={trainingId === v.id}
                        onClick={() => void train(v.id)}
                      >
                        Train voice
                      </Button>
                    )}
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      className="ml-auto"
                      aria-label={previewingId === v.id ? "Stop preview" : "Preview voice"}
                      onClick={() => void preview(v)}
                    >
                      {previewingId === v.id ? (
                        <Spinner className="size-4" />
                      ) : (
                        <Play />
                      )}
                    </Button>
                    {v.owner_id === user?.id && (
                      <Button
                        size="icon-sm"
                        variant="destructive"
                        aria-label="Delete voice"
                        onClick={() => void remove(v.id)}
                      >
                        <Trash2 />
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
              ))}
            </div>
          );
        })()}
      </div>
    </PageContainer>
  );
}
