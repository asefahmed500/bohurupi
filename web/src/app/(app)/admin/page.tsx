"use client";

// Admin (role-gated, FR-9): engine health + toggles, usage charts,
// voice moderation, users.

import * as React from "react";
import { toast } from "sonner";
import {
  Bar,
  BarChart,
  CartesianGrid,
  XAxis,
  YAxis,
} from "recharts";

import {
  adminEngines,
  adminPendingVoices,
  adminModerate,
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
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ChartContainer } from "@/components/ui/chart";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
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

export default function AdminPage() {
  const { user, ready } = useApp();
  const [tab, setTab] = React.useState("overview");
  const [engines, setEngines] = React.useState<EngineStatus[] | null>(null);
  const [usage, setUsage] = React.useState<Awaited<ReturnType<typeof adminUsage>> | null>(null);
  const [stats, setStats] = React.useState<Awaited<ReturnType<typeof adminStats>> | null>(null);
  const [users, setUsers] = React.useState<Awaited<ReturnType<typeof adminUsers>> | null>(null);
  const [pending, setPending] = React.useState<Voice[]>([]);

  const loadAll = React.useCallback(async () => {
    try {
      const [e, u, s] = await Promise.all([adminEngines(), adminUsage(30), adminStats()]);
      setEngines(e.engines);
      setUsage(u);
      setStats(s);
    } catch {
      toast.error("Could not load admin data");
    }
    try {
      const pv = await adminPendingVoices();
      setPending(pv.voices);
      setUsers(await adminUsers());
    } catch {
      /* non-admin */
    }
  }, []);

  React.useEffect(() => {
    if (ready && user?.role === "admin") void loadAll();
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
    try {
      await adminModerate(voiceId, decision);
      setPending((prev) => prev.filter((v) => v.id !== voiceId));
      toast.success(`Voice ${decision}d`);
    } catch {
      toast.error("Moderation failed");
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
                  <p className="mt-1 text-2xl font-semibold tabular-nums">
                    {s.value ?? <Skeleton className="h-7 w-14" />}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
          <Card className="bg-gradient-card">
            <CardHeader>
              <CardTitle className="text-base">Spoken seconds (last 14 days)</CardTitle>
              <CardDescription>Sum of synthesized audio across all users.</CardDescription>
            </CardHeader>
            <CardContent>
              {chartData.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">No usage yet</p>
              ) : (
                <ChartContainer
                  config={{ seconds: { label: "Seconds", color: "oklch(0.227 0 0)" } }}
                  className="h-64 w-full"
                >
                  <BarChart data={chartData}>
                    <CartesianGrid vertical={false} strokeDasharray="3 3" />
                    <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={11} />
                    <YAxis tickLine={false} axisLine={false} fontSize={11} width={32} />
                    <Bar dataKey="seconds" fill="oklch(0.227 0 0)" radius={4} />
                  </BarChart>
                </ChartContainer>
              )}
            </CardContent>
          </Card>
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
                  <Button size="sm" onClick={() => void moderate(v.id, "approve")}>
                    Approve
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => void moderate(v.id, "reject")}>
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
                  <TableHead>Joined</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users?.users.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="max-w-48 truncate">{u.email}</TableCell>
                    <TableCell>{u.name}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{u.role}</Badge>
                    </TableCell>
                    <TableCell className="capitalize">{u.plan}</TableCell>
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
