import type { ReactNode } from "react";
import Link from "next/link";
import {
  ArrowRight,
  AudioLines,
  Globe2,
  Mic,
  Shuffle,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";

import { buttonVariants } from "@/components/ui/button";

// Public landing page. Every link goes somewhere real — no decorative controls.
export default function LandingPage() {
  return (
    <main className="min-h-dvh bg-gradient-clean">
      {/* ── Pill navbar ───────────────────────────────────────────── */}
      <header className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 pt-5 sm:px-6">
        <Link href="/" className="flex items-center gap-2">
          <span className="flex size-9 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Mic className="size-4" />
          </span>
          <span className="text-sm font-semibold tracking-tight">Bohurupi</span>
        </Link>

        <nav
          aria-label="Primary"
          className="hidden items-center gap-1 rounded-md border bg-card/80 px-2 py-1 shadow-sm md:flex"
        >
          <a href="#features" className="rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            Features
          </a>
          <a href="#demo" className="rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            Demo
          </a>
          <a href="#languages" className="rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            Languages
          </a>
        </nav>

        <div className="flex items-center gap-2">
          <Link href="/login" className={buttonVariants({ variant: "ghost", size: "sm" })}>
            Sign in
          </Link>
          <Link href="/register" className={buttonVariants({ size: "sm", className: "px-4" })}>
            Get started
            <ArrowRight data-icon="inline-end" />
          </Link>
        </div>
      </header>

      {/* ── Hero ──────────────────────────────────────────────────── */}
      <section className="mx-auto grid max-w-6xl items-center gap-12 px-4 pt-18 pb-14 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] lg:pt-24">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1 text-xs text-muted-foreground">
            <Sparkles className="size-3" /> Any language, any voice
          </span>
          <h1 className="mt-5 text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl lg:text-6xl">
            Say anything.
            <br />
            <span className="text-muted-foreground">Hear it your way.</span>
          </h1>
          <p className="mt-5 max-w-sm text-sm leading-relaxed text-muted-foreground">
            Type or speak. Get a spoken reply in your language.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Link href="/register" className={buttonVariants({ size: "lg" })}>
              Start talking <ArrowRight data-icon="inline-end" />
            </Link>
            <a href="#demo" className={buttonVariants({ variant: "outline", size: "lg" })}>
              See demo
            </a>
          </div>
          <div id="languages" className="mt-9 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Globe2 className="size-3.5" />
            <span>55 languages</span>
            <span className="text-border">·</span>
            <span>বাংলা</span>
            <span>हिन्दी</span>
            <span>العربية</span>
            <span>English</span>
          </div>
        </div>

        {/* illustrative sound canvas — no fake controls */}
        <div aria-hidden className="relative mx-auto w-full max-w-md">
          <div className="rounded-[2rem] border bg-gradient-card p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Voice preview</span>
              <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">বাংলা · বহুরূপী</span>
            </div>
            <div className="mt-8 flex h-32 items-center justify-center gap-1.5">
              {[10, 22, 38, 58, 82, 64, 44, 70, 92, 52, 34, 62, 40, 24, 12].map((h, i) => (
                <span
                  key={i}
                  className="w-1.5 rounded-full bg-foreground/80"
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
            <div className="mt-8 flex items-center gap-3 border-t pt-4">
              <span className="flex size-8 items-center justify-center rounded-full bg-secondary">
                <AudioLines className="size-4 text-muted-foreground" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">Spoken with Kokoro</p>
                <p className="text-[10px] text-muted-foreground">Reply · 4.2 s</p>
              </div>
              <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-muted-foreground">OK</span>
            </div>
          </div>
          <div className="absolute -right-3 -bottom-4 rotate-3 rounded-2xl border bg-card px-4 py-2 text-xs shadow-sm">
            “আমি বহুরূপীকে অনুমতি দিচ্ছি” ✦
          </div>
        </div>
      </section>

      {/* ── Demo card + features ─────────────────────────────────── */}
      <section id="demo" className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <div className="overflow-hidden rounded-3xl border bg-gradient-card shadow-sm">
          <div className="grid lg:grid-cols-[1fr_1fr]">
            <div className="border-b p-6 sm:p-8 lg:border-r lg:border-b-0">
              <p className="text-xs font-medium text-muted-foreground">Example conversation</p>
              <div className="mt-6 space-y-4">
                <div className="ml-auto w-fit max-w-sm rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground">
                  অ্যামাকে ইংরেজিতে বলো, “আজকের দিন কেমন?”
                </div>
                <div className="w-fit max-w-sm rounded-2xl border bg-card px-4 py-2.5 text-sm">
                  <p>Today looks bright — a good day to try a new voice.</p>
                  <div className="mt-3 flex h-6 items-center gap-1">
                    {[8, 14, 24, 40, 28, 18, 34, 22, 12].map((h, i) => (
                      <span key={i} className="w-1 rounded-full bg-muted-foreground/50" style={{ height: `${h}px` }} />
                    ))}
                  </div>
                </div>
              </div>
              <p className="mt-6 text-xs text-muted-foreground">
                The reply is spoken — not just written.
              </p>
            </div>

            <div id="features" className="grid gap-px bg-border sm:grid-cols-2">
              <Feature
                icon={<Globe2 className="size-4" />}
                title="Any language"
                text="Type or talk in 55 languages."
              />
              <Feature
                icon={<Shuffle className="size-4" />}
                title="Change voice"
                text="Re-speak any reply instantly."
              />
              <Feature
                icon={<Mic className="size-4" />}
                title="Your cloned voice"
                text="Consent-gated, watermarked."
              />
              <Feature
                icon={<SlidersHorizontal className="size-4" />}
                title="Voice studio"
                text="Speed, pitch and effects."
              />
            </div>
          </div>
        </div>
      </section>

      {/* ── CTA ───────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <div className="flex flex-col items-center gap-5 rounded-3xl border bg-card px-6 py-12 text-center shadow-sm">
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Your voice, without borders.
          </h2>
          <p className="max-w-md text-sm text-muted-foreground">
            One account. Every language. Any voice.
          </p>
          <Link href="/register" className={buttonVariants({ size: "lg" })}>
            Create free account <ArrowRight data-icon="inline-end" />
          </Link>
        </div>
      </section>

      {/* ── Footer ────────────────────────────────────────────────── */}
      <footer className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 border-t px-4 py-8 text-xs text-muted-foreground sm:flex-row sm:px-6">
        <div className="flex items-center gap-2">
          <span className="flex size-6 items-center justify-center rounded-full bg-foreground text-background">
            <Mic className="size-3" />
          </span>
          <span className="font-medium text-foreground">Bohurupi</span>
        </div>
        <p>Made for every voice.</p>
        <p>© 2026 Bohurupi</p>
      </footer>
    </main>
  );
}

function Feature({
  icon,
  title,
  text,
}: {
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <div className="bg-card p-6">
      <span className="flex size-9 items-center justify-center rounded-full bg-secondary">
        {icon}
      </span>
      <h3 className="mt-4 text-sm font-semibold">{title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{text}</p>
    </div>
  );
}
