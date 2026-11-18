"use client";

// History: searchable conversations, export audio, delete (PRD §3.4.5).

import * as React from "react";
import Link from "next/link";
import { ArrowDownToLine, MessageCircle, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { deleteConversation, downloadAudio, getConversation, listConversations } from "@/lib/api";
import type { AudioAsset, Conversation } from "@/lib/types";
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
import { Skeleton } from "@/components/ui/skeleton";

export default function HistoryPage() {
  const [conversations, setConversations] = React.useState<Conversation[] | null>(null);
  const [query, setQuery] = React.useState("");
  const [assets, setAssets] = React.useState<Record<string, AudioAsset[]>>({});

  const load = React.useCallback(async () => {
    setConversations(null);
    try {
      const res = await listConversations();
      setConversations(res.conversations);
      // lazy-load the first conversation's audio for export buttons
      const top = res.conversations.slice(0, 5);
      const results = await Promise.allSettled(
        top.map((c) => getConversation(c.id))
      );
      const map: Record<string, AudioAsset[]> = {};
      results.forEach((r, i) => {
        if (r.status === "fulfilled") {
          const msgAssets = r.value.messages.flatMap((m) => m.audio ?? []);
          if (top[i]) map[top[i].id] = msgAssets;
        }
      });
      setAssets(map);
    } catch {
      setConversations([]);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const filtered = React.useMemo(() => {
    if (!conversations) return null;
    if (!query) return conversations;
    return conversations.filter((c) => c.title.toLowerCase().includes(query.toLowerCase()));
  }, [conversations, query]);

  const remove = async (id: string) => {
    try {
      await deleteConversation(id);
      setConversations((prev) => prev?.filter((c) => c.id !== id) ?? []);
      toast.success("Conversation deleted");
    } catch {
      toast.error("Delete failed");
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl p-4 sm:p-6">
      <h1 className="text-lg font-semibold tracking-tight">History</h1>
      <p className="text-sm text-muted-foreground">
        Every conversation and generated audio, searchable and exportable.
      </p>

      <Input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search conversations…"
        className="mt-4"
        aria-label="Search conversations"
      />

      <div className="mt-6 flex flex-col gap-3">
        {filtered === null ? (
          Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)
        ) : filtered.length === 0 ? (
          <Empty className="rounded-xl border bg-card">
            <EmptyHeader>
              <EmptyMedia>
                <MessageCircle />
              </EmptyMedia>
              <EmptyTitle>Nothing here yet</EmptyTitle>
              <EmptyDescription>Start a conversation and it will appear here.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          filtered.map((c) => (
            <Card key={c.id} className="bg-gradient-card py-0">
              <CardContent className="flex items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <Link
                    href="/"
                    className="block truncate text-sm font-medium hover:underline"
                  >
                    {c.title}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    {new Date(c.updated_at).toLocaleString()} · default{" "}
                    {c.default_lang === "auto" ? "auto" : c.default_lang}
                  </p>
                </div>
                {assets[c.id]?.slice(0, 2).map((a) => (
                  <Button
                    key={a.id}
                    size="icon-sm"
                    variant="ghost"
                    aria-label="Export audio"
                    onClick={() => void downloadAudio(a.id, c.title.slice(0, 20))}
                  >
                    <ArrowDownToLine />
                  </Button>
                ))}
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Delete conversation"
                  onClick={() => void remove(c.id)}
                >
                  <Trash2 />
                </Button>
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
