"use client";

// Conversations state shared between the app-shell sidebar (list) and the
// chat page (active conversation). One source of truth, one fetcher.

import * as React from "react";

import { listConversations } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { Conversation } from "@/lib/types";

interface ConversationsState {
  conversations: Conversation[];
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  refresh: () => Promise<Conversation[]>;
  upsert: (conv: Conversation) => void;
  remove: (id: string) => void;
}

const ConversationsContext = React.createContext<ConversationsState | null>(null);

export function useConversations(): ConversationsState {
  const ctx = React.useContext(ConversationsContext);
  if (!ctx) throw new Error("useConversations must be used inside <ConversationsProvider>");
  return ctx;
}

export function ConversationsProvider({ children }: { children: React.ReactNode }) {
  const { ready, user } = useApp();
  const [conversations, setConversations] = React.useState<Conversation[]>([]);
  const [activeId, setActiveId] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    try {
      const res = await listConversations();
      setConversations(res.conversations);
      return res.conversations;
    } catch {
      return [];
    }
  }, []);

  // fetch once per auth session, not per navigation
  React.useEffect(() => {
    if (ready && user) void refresh();
    else {
      setConversations([]);
      setActiveId(null);
    }
  }, [ready, user, refresh]);

  const upsert = React.useCallback((conv: Conversation) => {
    setConversations((prev) => [conv, ...prev.filter((c) => c.id !== conv.id)]);
  }, []);

  const remove = React.useCallback((id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
  }, []);

  const value = React.useMemo(
    () => ({
      conversations,
      activeId,
      setActiveId,
      refresh,
      upsert,
      remove,
    }),
    [conversations, activeId, refresh, upsert, remove]
  );

  return <ConversationsContext.Provider value={value}>{children}</ConversationsContext.Provider>;
}
