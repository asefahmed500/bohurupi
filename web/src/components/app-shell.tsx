"use client";

// The single application shell: Sidebar → Main Area → Page Content.
// Canonical hierarchy (task §3):
//   AppShell (SidebarProvider)
//   ├─ Sidebar — the ONLY sidebar: menu + route-aware conversations group
//   ├─ SidebarInset — main area; owns the route height contract:
//   │     • "/" (chat): fixed-height flex context (h-[100dvh-4rem] md:h-svh, overflow-hidden)
//   │     • everything else: normal document flow (min-h-svh, body scrolls)
//   └─ BottomTabs — mobile-only, overlays the inset's reserved pb-16
//
// Pages must NOT recreate the shell, sidebars, or viewport-height containers.
// Non-chat pages use <PageContainer>; chat is the one documented full-bleed page.

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  AudioLines,
  Clock,
  MessageCircle,
  Mic,
  Plus,
  Settings,
  ShieldCheck,
} from "lucide-react";

import { useApp } from "@/lib/store";
import { useConversations } from "@/lib/conversations";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar";

const NAV = [
  { href: "/chat", label: "Chat", icon: MessageCircle },
  { href: "/voices", label: "Voices", icon: Mic },
  { href: "/studio", label: "Studio", icon: AudioLines },
  { href: "/history", label: "History", icon: Clock },
  { href: "/settings", label: "Settings", icon: Settings },
];

function useNavItems() {
  const pathname = usePathname();
  const { user } = useApp();
  const items =
    user?.role === "admin"
      ? [...NAV, { href: "/admin", label: "Admin", icon: ShieldCheck }]
      : NAV;
  return { items, pathname };
}

function NavItems() {
  const { items, pathname } = useNavItems();
  return (
    <SidebarMenu>
      {items.map((item) => (
        <SidebarMenuItem key={item.href}>
          <SidebarMenuButton
            isActive={pathname === item.href}
            tooltip={item.label}
            render={<Link href={item.href} />}
          >
            <item.icon data-icon="inline-start" />
            <span>{item.label}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
  );
}

/** Conversations live INSIDE the single sidebar (route-aware group) — never a nested sidebar. */
function ConversationsGroup() {
  const { conversations, activeId, setActiveId } = useConversations();
  return (
    <SidebarGroup>
      <SidebarGroupLabel className="justify-between">
        Conversations
        <Button
          size="icon-xs"
          variant="ghost"
          aria-label="New conversation"
          onClick={() => setActiveId(null)}
        >
          <Plus />
        </Button>
      </SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {conversations.slice(0, 30).map((c) => (
            <SidebarMenuItem key={c.id}>
              <SidebarMenuButton isActive={activeId === c.id} onClick={() => setActiveId(c.id)}>
                <MessageCircle data-icon="inline-start" />
                <span className="truncate">{c.title}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
          {conversations.length === 0 && (
            <p className="px-2 py-1 text-xs text-muted-foreground">No conversations yet</p>
          )}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

function UserFooter() {
  const { user, logout } = useApp();
  if (!user) return null;
  const initials = (user.name || user.email).slice(0, 2).toUpperCase();
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <Avatar className="size-8">
        <AvatarFallback className="text-xs">{initials}</AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{user.name || user.email}</p>
        <p className="truncate text-xs text-muted-foreground capitalize">{user.plan} plan</p>
      </div>
      <Button variant="ghost" size="sm" className="text-xs" onClick={logout}>
        Sign out
      </Button>
    </div>
  );
}

function BottomTabs() {
  const { items, pathname } = useNavItems();
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 border-t bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80 md:hidden"
    >
      <div className="flex items-stretch justify-around overflow-x-auto px-1 pb-[env(safe-area-inset-bottom)]">
        {items.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={`flex min-w-14 shrink-0 flex-col items-center gap-0.5 rounded-md px-1.5 py-2 text-[10px] font-medium transition-colors ${
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <tab.icon className="size-5" />
              {tab.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { ready, user } = useApp();
  const pathname = usePathname();
  const router = useRouter();
  const isChat = pathname === "/chat";

  React.useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);

  if (!ready || !user) {
    return (
      <div className="flex min-h-dvh flex-col gap-4 p-6">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-4 w-64" />
        <Skeleton className="h-4 w-40" />
        <div className="flex flex-1 items-center justify-center">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Mic className="size-4" />
            <span className="text-sm">Bohurupi</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon" className="hidden md:flex">
        <SidebarHeader className="flex-row items-center gap-2 p-3">
          <Link href="/chat" className="flex min-w-0 flex-1 items-center gap-2 px-1 py-1">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Mic className="size-4" />
            </span>
            <span className="truncate text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">
              Bohurupi
            </span>
          </Link>
          <SidebarTrigger className="shrink-0" />
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Menu</SidebarGroupLabel>
            <SidebarGroupContent>
              <NavItems />
            </SidebarGroupContent>
          </SidebarGroup>
          {isChat && <ConversationsGroup />}
        </SidebarContent>
        <SidebarFooter>
          <Separator />
          <UserFooter />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
      <SidebarInset className="flex min-h-svh flex-col bg-gradient-clean pb-16 md:pb-0">
        {isChat ? (
          // Chat is the one documented full-bleed route: fixed-height flex context.
          // Mobile: subtract the bottom tab bar; tablet/desktop: full viewport.
          <div className="flex h-[calc(100dvh-4rem)] min-h-0 flex-col overflow-hidden md:h-svh">
            {children}
          </div>
        ) : (
          children
        )}
      </SidebarInset>
      <BottomTabs />
    </SidebarProvider>
  );
}
