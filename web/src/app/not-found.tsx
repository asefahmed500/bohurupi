import Link from "next/link";
import { Mic } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-gradient-clean p-6 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl border bg-card">
        <Mic className="size-6 text-muted-foreground" />
      </div>
      <div>
        <h1 className="text-xl font-semibold">Page not found</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          This page doesn&apos;t exist or has moved.
        </p>
      </div>
      <Link href="/" className={buttonVariants({ variant: "outline" })}>
        Back to chat
      </Link>
    </div>
  );
}
