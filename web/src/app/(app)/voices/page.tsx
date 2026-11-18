"use client";

// Voice library: presets, my voices, cloned — search + filters + play (PRD §3.4.2).

import * as React from "react";
import Link from "next/link";
import { Heart, Mic, Play, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { deleteVoice, listVoices } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { Voice } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function VoicesPage() {
  const { user } = useApp();
  const [voices, setVoices] = React.useState<Voice[] | null>(null);
  const [tab, setTab] = React.useState<"presets" | "mine">("presets");
  const [query, setQuery] = React.useState("");
  const [lang, setLang] = React.useState("all");
  const [gender, setGender] = React.useState("all");
  const [favorites, setFavorites] = React.useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("bohurupi.fav-voices") ?? "[]");
    } catch {
      return [];
    }
  });
  const { languages } = useApp();

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

  const remove = async (id: string) => {
    try {
      await deleteVoice(id);
      toast.success("Voice deleted");
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const toggleFav = (id: string) => {
    setFavorites((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      localStorage.setItem("bohurupi.fav-voices", JSON.stringify(next));
      return next;
    });
  };

  return (
    <div className="mx-auto w-full max-w-5xl p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Voice library</h1>
          <p className="text-sm text-muted-foreground">
            Presets by language, gender and style — plus your own cloned voices.
          </p>
        </div>
        <Button render={<Link href="/voices/clone" />}>
          <Plus data-icon="inline-start" />
          Clone a voice
        </Button>
      </div>

      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <Tabs value={tab} onValueChange={(v) => setTab(v as "presets" | "mine")}>
          <TabsList>
            <TabsTrigger value="presets">Presets</TabsTrigger>
            <TabsTrigger value="mine">My voices</TabsTrigger>
          </TabsList>
        </Tabs>
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
        {voices === null ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 9 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        ) : voices.length === 0 ? (
          <Empty className="rounded-xl border bg-card">
            <EmptyHeader>
              <EmptyMedia>
                <Mic />
              </EmptyMedia>
              <EmptyTitle>{tab === "mine" ? "No voices yet" : "No voices match"}</EmptyTitle>
              <EmptyDescription>
                {tab === "mine"
                  ? "Clone your own voice from a 10–30 second sample, or use presets."
                  : "Try different search or filters."}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {voices.map((v) => (
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
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      className="ml-auto"
                      aria-label="Preview sample"
                      onClick={() => toast.info("Preview: pick this voice in chat to hear it")}
                    >
                      <Play />
                    </Button>
                    {v.owner_id === user?.id && (
                      <Button
                        size="icon-sm"
                        variant="ghost"
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
        )}
      </div>
    </div>
  );
}
