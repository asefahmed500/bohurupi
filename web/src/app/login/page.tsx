"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { API_URL, getDemoAccounts, getHealth } from "@/lib/api";
import { useApp } from "@/lib/store";
import { AuthShell } from "@/components/auth-shell";
import { Button, buttonVariants } from "@/components/ui/button";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export default function LoginPage() {
  const { user, ready, login, loginDemo } = useApp();
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [googleEnabled, setGoogleEnabled] = React.useState(false);
  const [demoAccounts, setDemoAccounts] = React.useState<{ email: string; label: string }[]>([]);

  React.useEffect(() => {
    if (ready && user) router.replace("/chat");
  }, [ready, user, router]);

  React.useEffect(() => {
    getHealth()
      .then((h) => {
        setGoogleEnabled(h.oauth_google);
        if (h.demo) {
          getDemoAccounts().then(setDemoAccounts).catch(() => undefined);
        }
      })
      .catch(() => undefined);
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email, password);
      router.replace("/chat");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  const signInWithDemo = async (value: string) => {
    if (!value) return;
    setBusy(true);
    try {
      await loginDemo();
      toast.success("Signed in to the demo account");
      router.replace("/chat");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Demo sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title="Welcome back" description="Sign in to continue.">
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
        <Field>
          <FieldLabel htmlFor="password">Password</FieldLabel>
          <Input
            id="password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </Field>
        <Button type="submit" loading={busy} className="w-full">
          Sign in
        </Button>
      </form>

      <div className="mt-3 flex items-center justify-end text-xs">
        <Link href="/forgot-password" className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
          Forgot password?
        </Link>
      </div>

      {demoAccounts.length > 0 && (
        <div className="mt-5 border-t pt-4">
          <FieldLabel className="text-xs text-muted-foreground">Try the demo</FieldLabel>
          <Select onValueChange={(v) => void signInWithDemo(String(v ?? ""))} disabled={busy}>
            <SelectTrigger className="mt-2 w-full" aria-label="Demo account">
              <SelectValue placeholder="Choose a demo account" />
            </SelectTrigger>
            <SelectContent>
              {demoAccounts.map((a) => (
                <SelectItem key={a.email} value={a.email}>
                  {a.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {googleEnabled && (
        <a
          href={`${API_URL}/auth/google/login`}
          className={`${buttonVariants({ variant: "outline" })} mt-4 w-full`}
        >
          Continue with Google
        </a>
      )}

      <p className="mt-5 text-center text-xs text-muted-foreground">
        New here?{" "}
        <Link href="/register" className="text-foreground underline-offset-4 hover:underline">
          Create an account
        </Link>
      </p>
    </AuthShell>
  );
}
