"use client";

import * as React from "react";
import Link from "next/link";
import { toast } from "sonner";

import { forgotPassword } from "@/lib/api";
import { AuthShell } from "@/components/auth-shell";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

export default function ForgotPasswordPage() {
  const [email, setEmail] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [devUrl, setDevUrl] = React.useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await forgotPassword(email);
      setDevUrl(res.dev_url ?? null);
      toast.success(res.message);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title="Reset password" description="Enter your email — we'll send a reset link.">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field>
          <FieldLabel htmlFor="email">Email</FieldLabel>
          <Input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            placeholder="you@example.com"
          />
        </Field>
        <Button type="submit" loading={busy} className="w-full">
          Send reset link
        </Button>
      </form>

      {devUrl && (
        <p className="mt-4 rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
          Local development: no email provider is configured.{" "}
          <Link href={devUrl} className="text-foreground underline-offset-4 hover:underline">
            Open your reset link
          </Link>
          .
        </p>
      )}

      <p className="mt-5 text-center text-xs text-muted-foreground">
        <Link href="/login" className="text-foreground underline-offset-4 hover:underline">
          Back to sign in
        </Link>
      </p>
    </AuthShell>
  );
}
