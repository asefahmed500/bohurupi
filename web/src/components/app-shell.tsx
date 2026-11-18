"use client";

// Authenticated app chrome: sidebar on tablet/desktop, bottom tabs on phones.
// Breakpoints follow PRD §3.3: 360 / 768 / 1200.

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  AudioLines,
  Clock,
  LayoutDashboard,
  MessageCircle,
  Mic,
  Settings,
  ShieldCheck,
} from "lucide-react";

import { useApp } from "@/lib/store";
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
} from "@/components/ui/sidebar";

const NAV = [
  { href: "/", label: "Chat", icon: MessageCircle },
  { href: "/voices", label: "Voices", icon: Mic },
  { href: "/studio", label: "Studio", icon: AudioLines },
  { href: "/history", label: "History", icon: Clock },
  { href: "/settings", label: "Settings", icon: Settings },
];

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user } = useApp();
  const items = user?.role === "admin" ? [...NAV, { href: "/admin", label: "Admin", icon: ShieldCheck }] : NAV;
  return (
    <SidebarMenu>
      {items.map((item) => (
        <SidebarMenuItem key={item.href}>
          <SidebarMenuButton
            isActive={pathname === item.href}
            tooltip={item.label}
            render={
              <Link href={item.href} onClick={onNavigate} />
            }
          >
            <item.icon data-icon="inline-start" />
            <span>{item.label}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </SidebarMenu>
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
  const pathname = usePathname();
  const { user } = useApp();
  const tabs = user?.role === "admin" ? [...NAV, { href: "/admin", label: "Admin", icon: ShieldCheck }] : NAV;
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 border-t bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80 md:hidden"
    >
      <div className="mx-auto flex max-w-xl items-stretch justify-around px-2 pb-[env(safe-area-inset-bottom)]">
        {tabs.slice(0, 5).map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={`flex min-w-14 flex-col items-center gap-0.5 rounded-md px-2 py-2 text-[10px] font-medium transition-colors ${
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
  const router = useRouter();

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
        <SidebarHeader className="p-3">
          <Link href="/" className="flex items-center gap-2 px-2 py-1">
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Mic className="size-4" />
            </span>
            <span className="text-sm font-semibold tracking-tight">Bohurupi</span>
          </Link>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Menu</SidebarGroupLabel>
            <SidebarGroupContent>
              <NavItems />
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <Separator />
          <UserFooter />
        </SidebarFooter>
      </Sidebar>
      <SidebarInset className="pb-16 md:pb-0 bg-gradient-clean min-h-dvh">
        {children}
      </SidebarInset>
      <BottomTabs />
    </SidebarProvider>
  );
}
