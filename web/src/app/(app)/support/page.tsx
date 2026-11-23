"use client";

// Customer-support agent: choose a business, chat with its knowledge-grounded
// agent, and see when a human ticket was created.

import * as React from "react";
import { MessageCircle, Send, Ticket } from "lucide-react";
import { toast } from "sonner";

import { publicBusinesses, supportChat } from "@/lib/api";
import { PageContainer, PageHeader } from "@/components/page-container";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

type Turn = { role: "user" | "agent"; text: string; ticket?: string | null };

export default function SupportPage() {
  const [businesses, setBusinesses] = React.useState<{ slug: string; name: string }[] | null>(null);
  const [slug, setSlug] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [text, setText] = React.useState("");
  const [conversationId, setConversationId] = React.useState<string | null>(null);
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    publicBusinesses()
      .then((res) => {
        setBusinesses(res.businesses);
        if (res.businesses.length > 0 && !slug) setSlug(res.businesses[0].slug);
      })
      .catch(() => setBusinesses([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = async () => {
    if (!text.trim() || !slug || busy) return;
    const message = text.trim();
    setTurns((prev) => [...prev, { role: "user", text: message }]);
    setText("");
    setBusy(true);
    try {
      const res = await supportChat({
        business_slug: slug,
        message,
        email: email.trim() || undefined,
        conversation_id: conversationId ?? undefined,
      });
      setConversationId(res.conversation_id);
      setTurns((prev) => [
        ...prev,
        { role: "agent", text: res.reply, ticket: res.ticket_id },
      ]);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageContainer size="default">
      <PageHeader
        title="Support agent"
        description="Knowledge-grounded answers in any language — with human escalation."
      />

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-base">Start a conversation</CardTitle>
          <CardDescription>
            Pick a business; its published knowledge base powers the answers.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field>
              <FieldLabel>Business</FieldLabel>
              {businesses === null ? (
                <Skeleton className="h-9 w-full" />
              ) : businesses.length === 0 ? (
                <p className="text-sm text-muted-foreground">No businesses configured yet.</p>
              ) : (
                <Select value={slug} onValueChange={(v) => setSlug(String(v ?? ""))}>
                  <SelectTrigger aria-label="Business" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {businesses.map((b) => (
                      <SelectItem key={b.slug} value={b.slug}>
                        {b.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
            <Field>
              <FieldLabel htmlFor="support-email">Your email (optional)</FieldLabel>
              <Input
                id="support-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </Field>
          </div>

          <div className="flex min-h-56 flex-col gap-2 rounded-md border bg-muted/20 p-3">
            {turns.length === 0 && (
              <div className="m-auto flex flex-col items-center gap-2 text-center text-sm text-muted-foreground">
                <MessageCircle className="size-6" />
                Ask a question to get started.
              </div>
            )}
            {turns.map((turn, i) => (
              <div
                key={i}
                className={`max-w-[85%] rounded-md px-3 py-2 text-sm ${
                  turn.role === "user"
                    ? "ml-auto bg-primary text-primary-foreground"
                    : "bg-card"
                }`}
              >
                {turn.text}
                {turn.ticket && (
                  <p className="mt-2 flex items-center gap-1 text-xs opacity-80">
                    <Ticket className="size-3" /> Human ticket created
                  </p>
                )}
              </div>
            ))}
          </div>

          <div className="flex gap-2">
            <Input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
              placeholder="Ask about refunds, shipping, policies…"
              aria-label="Support message"
              disabled={!slug}
            />
            <Button onClick={() => void send()} loading={busy} disabled={!text.trim() || !slug}>
              <Send data-icon="inline-start" />
              Send
            </Button>
          </div>
        </CardContent>
      </Card>
    </PageContainer>
  );
}
