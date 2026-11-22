"use client";

// Admin (role-gated, FR-9): engine health + toggles, usage charts,
// voice moderation, users.

import * as React from "react";
import dynamic from "next/dynamic";
import { toast } from "sonner";

import {
  adminEngines,
  adminPendingVoices,
  adminModerate,
  adminPatchUser,
  adminSetEngine,
  adminStats,
  adminUsage,
  adminUsers,
} from "@/lib/api";
import { useApp } from "@/lib/store";
import type { EngineStatus, Voice } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageContainer, PageHeader } from "@/components/page-container";

// heavy chart (recharts) loads only when the overview renders one
const UsageChart = dynamic(() => import("./usage-chart"), {
  ssr: false,
  loading: () => <Skeleton className="h-64 w-full" />,
});

type AdminUser = {
  id: string;
  email: string;
  name: string;
  role: string;
  plan: string;
  is_active: boolean;
  created_at: string;
};

export default function AdminPage() {
  const { user, ready } = useApp();
  const [tab, setTab] = React.useState("overview");
  const [engines, setEngines] = React.useState<EngineStatus[] | null>(null);
  const [usage, setUsage] = React.useState<Awaited<ReturnType<typeof adminUsage>> | null>(null);
  const [stats, setStats] = React.useState<Awaited<ReturnType<typeof adminStats>> | null>(null);
  const [users, setUsers] = React.useState<AdminUser[] | null>(null);
  const [pending, setPending] = React.useState<Voice[]>([]);

  const loadAll = React.useCallback(async () => {
    try {
      const [e, u, s, pv, usersRes] = await Promise.all([
        adminEngines(),
        adminUsage(30),
        adminStats(),
        adminPendingVoices(),
        adminUsers(),
      ]);
      setEngines(e.engines);
      setUsage(u);
      setStats(s);
      setPending(pv.voices);
      setUsers(usersRes.users);
    } catch {
      toast.error("Could not load admin data");
    }
  }, []);

  React.useEffect(() => {
    if (ready && user?.role === "admin") {
      // async data load kicked off from the effect — safe by construction
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void loadAll();
    }
  }, [ready, user, loadAll]);

  if (!ready) return <Skeleton className="m-6 h-40 rounded-xl" />;
  if (user?.role !== "admin") {
    return (
      <div className="p-6">
        <p className="text-sm text-muted-foreground">Admin access required.</p>
      </div>
    );
  }

  const toggleEngine = async (name: string, enabled: boolean) => {
    try {
      await adminSetEngine(name, enabled);
      setEngines((prev) => prev?.map((e) => (e.name === name ? { ...e, enabled } : e)) ?? null);
      toast.success(`${name} ${enabled ? "enabled" : "disabled"}`);
    } catch {
      toast.error("Could not update engine");
    }
  };

  const moderate = async (voiceId: string, decision: "approve" | "reject") => {
    if (
      decision === "reject" &&
      !confirm("Reject this voice? The uploaded sample and consent audio are deleted permanently.")
    ) {
      return;
    }
    try {
      await adminModerate(voiceId, decision);
      setPending((prev) => prev.filter((v) => v.id !== voiceId));
      toast.success(`Voice ${decision}d`);
    } catch {
      toast.error("Moderation failed");
    }
  };

  const patchUser = async (
    id: string,
    patch: { role?: string; plan?: string; is_active?: boolean }
  ) => {
    try {
      const updated = await adminPatchUser(id, patch);
      setUsers((prev) => prev?.map((u) => (u.id === id ? { ...u, ...updated } : u)) ?? null);
      toast.success("User updated");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not update user");
    }
  };

  const chartData = usage
    ? Object.entries(usage.by_day).slice(-14).map(([day, v]) => ({
        day: day.slice(5),
        seconds: Math.round(v.seconds),
        chars: v.chars,
      }))
    : [];

  return (
    <PageContainer size="wide">
      <PageHeader
        title="Admin"
        description="Engines, usage, moderation, users."
        actions={
          <Button variant="outline" size="sm" onClick={() => void loadAll()}>
            Refresh
          </Button>
        }
      />

      <Tabs value={tab} onValueChange={setTab} className="mt-4">
        <TabsList className="h-auto w-full flex-wrap">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="engines">Engines</TabsTrigger>
          <TabsTrigger value="moderation">
            Moderation{pending.length > 0 ? ` (${pending.length})` : ""}
          </TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === "overview" && (
        <div className="mt-6 flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              { label: "Users", value: stats?.users },
              { label: "Conversations", value: stats?.conversations },
              { label: "Messages", value: stats?.messages },
              { label: "TTS minutes (30d)", value: usage ? Math.round(usage.totals.seconds / 60) : undefined },
            ].map((s) => (
              <Card key={s.label} className="bg-gradient-card py-0">
                <CardContent className="p-4">
                  <p className="text-xs text-muted-foreground">{s.label}</p>
                  {s.value === undefined ? (
                    <Skeleton className="mt-1 h-7 w-14" />
                  ) : (
                    <p className="mt-1 text-2xl font-semibold tabular-nums">{s.value}</p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
          <UsageChart data={chartData} />
        </div>
      )}

      {tab === "engines" && (
        <div className="mt-6 flex flex-col gap-3">
          {engines === null ? (
            <Skeleton className="h-32 rounded-xl" />
          ) : (
            engines.map((e) => (
              <Card key={e.name} className="bg-gradient-card py-0">
                <CardContent className="flex items-center gap-3 p-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium capitalize">{e.name}</p>
                      <Badge variant={e.healthy && e.enabled ? "secondary" : "destructive"}>
                        {!e.enabled ? "disabled" : e.healthy ? "healthy" : "down"}
                      </Badge>
                    </div>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {e.languages.length} languages · quality rank {e.quality_rank}
                    </p>
                  </div>
                  <Switch
                    checked={e.enabled}
                    onCheckedChange={(v) => void toggleEngine(e.name, v)}
                    aria-label={`Toggle ${e.name}`}
                  />
                </CardContent>
              </Card>
            ))
          )}
          <p className="text-xs text-muted-foreground">
            Disabling an engine removes it from the fallback chain immediately.
          </p>
        </div>
      )}

      {tab === "moderation" && (
        <div className="mt-6 flex flex-col gap-3">
          {pending.length === 0 ? (
            <Card className="bg-gradient-card">
              <CardContent className="p-6 text-center text-sm text-muted-foreground">
                No voices waiting for review.
              </CardContent>
            </Card>
          ) : (
            pending.map((v) => (
              <Card key={v.id} className="bg-gradient-card py-0">
                <CardContent className="flex flex-wrap items-center gap-3 p-4">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{v.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {v.languages.join(", ")} · submitted by {v.owner_id?.slice(0, 8)}
                    </p>
                  </div>
                  <Button size="sm" variant="success" onClick={() => void moderate(v.id, "approve")}>
                    Approve
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => void moderate(v.id, "reject")}>
                    Reject
                  </Button>
                </CardContent>
              </Card>
            ))
          )}
          <Separator />
          <p className="text-xs text-muted-foreground">
            Rejecting permanently deletes the uploaded sample and consent audio.
          </p>
        </div>
      )}

      {tab === "users" && (
        <Card className="bg-gradient-card mt-6 py-0">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Plan</TableHead>
                  <TableHead>Active</TableHead>
                  <TableHead>Joined</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users?.map((u) => (
                  <TableRow key={u.id} className={u.is_active ? undefined : "opacity-60"}>
                    <TableCell className="max-w-48 truncate">{u.email}</TableCell>
                    <TableCell>{u.name}</TableCell>
                    <TableCell>
                      <Select
                        value={u.role}
                        onValueChange={(v) => v && v !== u.role && void patchUser(u.id, { role: v })}
                      >
                        <SelectTrigger size="sm" className="w-24 border-none shadow-none" aria-label={`Role for ${u.email}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="user">user</SelectItem>
                          <SelectItem value="admin">admin</SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>
                      <Select
                        value={u.plan}
                        onValueChange={(v) => v && v !== u.plan && void patchUser(u.id, { plan: v })}
                      >
                        <SelectTrigger size="sm" className="w-24 border-none shadow-none capitalize" aria-label={`Plan for ${u.email}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="free">free</SelectItem>
                          <SelectItem value="pro">pro</SelectItem>
                          <SelectItem value="studio">studio</SelectItem>
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>
                      <Switch
                        checked={u.is_active}
                        onCheckedChange={(v) => void patchUser(u.id, { is_active: v })}
                        aria-label={`Active for ${u.email}`}
                      />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(u.created_at).toLocaleDateString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </PageContainer>
  );
}
