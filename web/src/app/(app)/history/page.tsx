"use client";

// History: searchable conversations, export audio, delete (PRD §3.4.5).

import * as React from "react";
import { useRouter } from "next/navigation";
import { ArrowDownToLine, MessageCircle, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  clearHistory,
  deleteConversation,
  downloadAudio,
  getConversation,
  listConversations,
} from "@/lib/api";
import { useConversations } from "@/lib/conversations";
import type { Conversation } from "@/lib/types";
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
import { PageContainer, PageHeader } from "@/components/page-container";

export default function HistoryPage() {
  const router = useRouter();
  const { setActiveId } = useConversations();
  const [conversations, setConversations] = React.useState<Conversation[] | null>(null);
  const [query, setQuery] = React.useState("");
  const [exportingId, setExportingId] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const res = await listConversations();
      setConversations(res.conversations);
    } catch {
      setConversations([]);
    }
  }, []);

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data fetch on mount
    void load();
  }, [load]);

  const filtered = React.useMemo(() => {
    if (!conversations) return null;
    if (!query) return conversations;
    return conversations.filter((c) => c.title.toLowerCase().includes(query.toLowerCase()));
  }, [conversations, query]);

  const remove = async (id: string) => {
    if (!confirm("Delete this conversation? Its messages and audio are removed permanently.")) {
      return;
    }
    try {
      await deleteConversation(id);
      setConversations((prev) => prev?.filter((c) => c.id !== id) ?? []);
      toast.success("Conversation deleted");
    } catch {
      toast.error("Delete failed");
    }
  };

  /** Fetch the conversation's audio on demand and download it (no preload). */
  const exportAudio = async (id: string, title: string) => {
    setExportingId(id);
    try {
      const data = await getConversation(id);
      const assets = data.messages.flatMap((m) => m.audio ?? []);
      if (assets.length === 0) {
        toast.info("This conversation has no audio to export yet");
        return;
      }
      for (const a of assets.slice(0, 5)) {
        await downloadAudio(a.id, title.slice(0, 20));
      }
      if (assets.length > 5) toast.info(`Exported the latest 5 of ${assets.length} clips`);
    } catch {
      toast.error("Export failed");
    } finally {
      setExportingId(null);
    }
  };

  const open = (id: string) => {
    setActiveId(id);
    router.push("/chat");
  };

  return (
    <PageContainer size="default">
      <PageHeader
        title="History"
        description="Every conversation and generated audio, searchable and exportable."
        actions={
          <Button
            variant="destructive"
            size="sm"
            disabled={!conversations || conversations.length === 0}
            onClick={() => {
              if (!confirm("Delete ALL your chat history? This cannot be undone.")) return;
              void clearHistory()
                .then((res) => {
                  toast.success(`Deleted ${res.deleted} conversation(s)`);
                  return load();
                })
                .catch(() => toast.error("Could not clear history"));
            }}
          >
            <Trash2 data-icon="inline-start" />
            Clear all
          </Button>
        }
      />

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
                  <button
                    type="button"
                    onClick={() => open(c.id)}
                    className="block max-w-full truncate text-left text-sm font-medium hover:underline"
                  >
                    {c.title}
                  </button>
                  <p className="text-xs text-muted-foreground">
                    {new Date(c.updated_at).toLocaleString()} · default{" "}
                    {c.default_lang === "auto" ? "auto" : c.default_lang}
                  </p>
                </div>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Export audio"
                  disabled={exportingId === c.id}
                  onClick={() => void exportAudio(c.id, c.title)}
                >
                  <ArrowDownToLine />
                </Button>
                <Button
                  size="icon-sm"
                  variant="destructive"
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
    </PageContainer>
  );
}
