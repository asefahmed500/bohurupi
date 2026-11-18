import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { ConversationsProvider } from "@/lib/conversations";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <ConversationsProvider>
      <AppShell>{children}</AppShell>
    </ConversationsProvider>
  );
}
