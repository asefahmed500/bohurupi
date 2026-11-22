"use client";

// Searchable voice picker — side Sheet on desktop, bottom Drawer on phones.

import * as React from "react";
import { Check, Mic, Search } from "lucide-react";

import { listVoices } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { Voice } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer";
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { useIsMobile } from "@/hooks/use-mobile";

function VoiceRow({
  voice,
  selected,
  onSelect,
}: {
  voice: Voice;
  selected: boolean;
  onSelect: (v: Voice) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={() => onSelect(voice)}
      className={`flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors ${
        selected
          ? "border-foreground/40 bg-accent"
          : "border-transparent bg-card hover:bg-accent/60"
      }`}
    >
      <span
        aria-hidden
        className="flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary text-foreground/70"
      >
        {voice.gender === "female" ? "F" : voice.gender === "male" ? "M" : "·"}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{voice.name}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {voice.engine} · {voice.languages.slice(0, 4).join(", ")}
          {voice.languages.length > 4 ? ` +${voice.languages.length - 4}` : ""}
        </span>
      </span>
      {selected && <Check className="size-4 shrink-0" />}
    </button>
  );
}

function VoiceList({
  selectedId,
  onSelect,
  langFilter,
  onLangChange,
}: {
  selectedId: string;
  onSelect: (v: Voice) => void;
  langFilter: string;
  onLangChange: (v: string) => void;
}) {
  const [voices, setVoices] = React.useState<Voice[] | null>(null);
  const [query, setQuery] = React.useState("");
  const [gender, setGender] = React.useState("all");
  const { languages } = useApp();

  React.useEffect(() => {
    let cancelled = false;
    // loading placeholder reset per filter change
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVoices(null);
    listVoices({ lang: langFilter === "all" ? undefined : langFilter })
      .then((res) => {
        if (!cancelled) setVoices(res.voices);
      })
      .catch(() => {
        if (!cancelled) setVoices([]);
      });
    return () => {
      cancelled = true;
    };
  }, [langFilter]);

  const filtered = React.useMemo(() => {
    if (!voices) return null;
    return voices.filter((v) => {
      if (gender !== "all" && v.gender !== gender) return false;
      if (query && !v.name.toLowerCase().includes(query.toLowerCase())) return false;
      return true;
    });
  }, [voices, query, gender]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search voices"
            className="pl-8"
            aria-label="Search voices"
          />
        </div>
        <Select value={gender} onValueChange={(v) => v && setGender(v)}>
          <SelectTrigger className="w-28" aria-label="Gender filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="female">Female</SelectItem>
            <SelectItem value="male">Male</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <Select value={langFilter} onValueChange={(v) => v && onLangChange(v)}>
        <SelectTrigger aria-label="Language filter">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Any language</SelectItem>
          {languages.map((l) => (
            <SelectItem key={l.code} value={l.code}>
              {l.native} · {l.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Separator />
      <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1 pb-2">
        {filtered === null ? (
          <div className="flex flex-col gap-2 pt-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <Empty className="py-10">
            <EmptyHeader>
              <EmptyTitle>No voices found</EmptyTitle>
              <EmptyDescription>
                Try clearing the filters, or clone your own voice.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="flex flex-col gap-2 pt-1">
            {filtered.map((v) => (
              <VoiceRow key={v.id} voice={v} selected={v.id === selectedId} onSelect={onSelect} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function VoicePicker({
  value,
  onChange,
  trigger,
  title = "Choose a voice",
}: {
  value: string;
  onChange: (voice: Voice) => void;
  trigger: React.ReactElement;
  title?: string;
}) {
  const isMobile = useIsMobile();
  const [open, setOpen] = React.useState(false);
  const [langFilter, setLangFilter] = React.useState("all");

  const content = (
    <VoiceList
      selectedId={value}
      langFilter={langFilter}
      onLangChange={setLangFilter}
      onSelect={(v) => {
        onChange(v);
        setOpen(false);
      }}
    />
  );

  if (isMobile) {
    return (
      <Drawer open={open} onOpenChange={setOpen}>
        <DrawerTrigger render={trigger} />
        <DrawerContent className="flex h-[85dvh] flex-col">
          <DrawerHeader className="pb-2">
            <DrawerTitle>{title}</DrawerTitle>
            <DrawerDescription>Filter by language, gender or name.</DrawerDescription>
          </DrawerHeader>
          <div className="flex min-h-0 flex-1 flex-col px-4 pb-6">{content}</div>
        </DrawerContent>
      </Drawer>
    );
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger render={trigger} />
      <SheetContent side="right" className="flex w-[380px] flex-col gap-0 sm:max-w-[380px]">
        <SheetHeader className="pb-2">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>Filter by language, gender or name.</SheetDescription>
        </SheetHeader>
        <div className="flex min-h-0 flex-1 flex-col pb-4">{content}</div>
      </SheetContent>
    </Sheet>
  );
}

export function VoiceChip({
  voiceName,
  loading,
}: {
  voiceName?: string;
  loading?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1 text-xs font-medium">
      {loading ? <Spinner className="size-3" /> : <Mic className="size-3" />}
      {voiceName ?? "Voice"}
    </span>
  );
}

export function VoicePickerButton({
  value,
  onChange,
  voiceName,
}: {
  value: string;
  onChange: (v: Voice) => void;
  voiceName?: string;
}) {
  return (
    <VoicePicker
      value={value}
      onChange={onChange}
      trigger={
        <Button variant="outline" size="sm">
          <Mic data-icon="inline-start" />
          <span className="max-w-32 truncate">{voiceName ?? "Voice"}</span>
        </Button>
      }
    />
  );
}
