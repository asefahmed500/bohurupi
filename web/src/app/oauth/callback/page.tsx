"use client";

// OAuth landing: captures the access token from the API redirect.

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { toast } from "sonner";

import { useApp } from "@/lib/store";
import { Spinner } from "@/components/ui/spinner";

function OAuthCallback() {
  const params = useSearchParams();
  const router = useRouter();
  const { setTokenFromOAuth, ready } = useApp();
  const ran = React.useRef(false);

  React.useEffect(() => {
    if (ran.current) return;
    const token = params.get("token") ?? location.hash.match(/token=([^&]+)/)?.[1];
    if (!token) {
      toast.error("Sign-in failed — no token");
      router.replace("/login");
      return;
    }
    ran.current = true;
    setTokenFromOAuth(token)
      .then(() => router.replace("/"))
      .catch(() => {
        toast.error("Sign-in failed");
        router.replace("/login");
      });
  }, [params, router, setTokenFromOAuth]);

  return (
    <div className="flex min-h-dvh items-center justify-center gap-2 text-muted-foreground">
      <Spinner className="size-4" />
      <span className="text-sm">Signing you in…</span>
    </div>
  );
}

export default function OAuthPage() {
  return (
    <Suspense fallback={<Spinner className="mx-auto mt-40" />}>
      <OAuthCallback />
    </Suspense>
  );
}
