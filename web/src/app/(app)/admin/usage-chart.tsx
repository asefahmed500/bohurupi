"use client";

// Usage chart, split into its own module so the heavy recharts bundle
// (349 KB raw) loads only when the admin overview actually shows a chart
// (perf audit finding #11).

import {
  Bar,
  BarChart,
  CartesianGrid,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer } from "@/components/ui/chart";

export default function UsageChart({
  data,
}: {
  data: { day: string; seconds: number; chars: number }[];
}) {
  return (
    <Card className="bg-gradient-card">
      <CardHeader>
        <CardTitle className="text-base">Spoken seconds (last 14 days)</CardTitle>
        <CardDescription>Sum of synthesized audio across all users.</CardDescription>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">No usage yet</p>
        ) : (
          <ChartContainer
            config={{ seconds: { label: "Seconds", color: "var(--chart-1)" } }}
            className="h-64 w-full"
          >
            <BarChart data={data}>
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={11} />
              <YAxis tickLine={false} axisLine={false} fontSize={11} width={32} />
              <Bar dataKey="seconds" fill="var(--chart-1)" radius={4} />
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  );
}
