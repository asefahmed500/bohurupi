"use client";

// Clone wizard (PRD §3.4.3):
// 1 Consent (checkbox + phrase) → 2 Record/upload → 3 Quality check → 4 Name+test.

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, CheckCircle2, Mic, Square, Upload } from "lucide-react";
import { toast } from "sonner";

import { cloneVoice, getConsentPhrase } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { MicButton } from "@/components/chat/mic-button";

export default function ClonePage() {
  const router = useRouter();
  const { languages, user } = useApp();
  const [step, setStep] = React.useState(1);
  const [consentGiven, setConsentGiven] = React.useState(false);
  const [consentLang, setConsentLang] = React.useState("en");
  const [phrase, setPhrase] = React.useState("");
  const [typedPhrase, setTypedPhrase] = React.useState("");
  const [sample, setSample] = React.useState<File | null>(null);
  const [consentAudio, setConsentAudio] = React.useState<File | null>(null);
  const [sampleLang, setSampleLang] = React.useState("en");
  const [voiceName, setVoiceName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [recording, setRecording] = React.useState(false);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<Blob[]>([]);
  const step2ConsentRef = React.useRef<Blob[]>([]);

  const stepMeta = ["Consent", "Sample", "Quality", "Finish"];

  const loadPhrase = React.useCallback(async (lang: string) => {
    try {
      const res = await getConsentPhrase(lang);
      setPhrase(res.phrase);
    } catch {
      setPhrase("");
    }
  }, []);

  React.useEffect(() => {
    void loadPhrase(consentLang);
  }, [consentLang, loadPhrase]);

  React.useEffect(() => {
    if (user) setVoiceName((n) => n || `${user.name || "My"}'s voice`);
  }, [user]);

  const startConsentRecording = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true }).catch(() => null);
    if (!stream) {
      toast.error("Microphone access denied");
      return;
    }
    const recorder = new MediaRecorder(stream);
    chunksRef.current = [];
    recorder.ondataavailable = (e) => chunksRef.current.push(e.data);
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
      step2ConsentRef.current = chunksRef.current;
      setConsentAudio(new File([blob], "consent.webm", { type: blob.type }));
    };
    recorder.start();
    recorderRef.current = recorder;
    setRecording(true);
  };

  const stopConsentRecording = () => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
  };

  const nextFromConsent = () => {
    if (!consentGiven) {
      toast.error("Please confirm you have the right to clone this voice");
      return;
    }
    if (typedPhrase.trim() !== phrase.trim()) {
      toast.error("Type the consent phrase exactly as written");
      return;
    }
    if (!consentAudio) {
      toast.error("Record yourself reading the consent phrase");
      return;
    }
    setStep(2);
  };

  const nextFromSample = () => {
    if (!sample) {
      toast.error("Record or upload a 10–30 second sample");
      return;
    }
    setStep(3); // quality check happens server-side on submit
  };

  const submit = async () => {
    if (!sample || !consentAudio) return;
    setBusy(true);
    try {
      const res = await cloneVoice(
        {
          name: voiceName.trim() || "My voice",
          consent: String(consentGiven),
          consent_lang: consentLang,
          consent_phrase_text: typedPhrase.trim(),
          sample_lang: sampleLang,
        },
        sample,
        consentAudio
      );
      toast.success(res.note);
      router.push("/voices");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Cloning failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-2xl p-4 sm:p-6">
      <Button variant="ghost" size="sm" className="mb-4">
        <Link href="/voices" className="flex items-center gap-1.5">
          <ArrowLeft className="size-4" />
          Voice library
        </Link>
      </Button>

      {/* steps */}
      <ol className="mb-6 flex items-center gap-2">
        {stepMeta.map((label, i) => (
          <li key={label} className="flex flex-1 items-center gap-2">
            <span
              className={`flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-medium ${
                step > i + 1
                  ? "border-transparent bg-primary text-primary-foreground"
                  : step === i + 1
                    ? "border-foreground bg-card"
                    : "bg-card text-muted-foreground"
              }`}
            >
              {step > i + 1 ? <CheckCircle2 className="size-4" /> : i + 1}
            </span>
            <span className={`text-xs ${step === i + 1 ? "font-medium" : "text-muted-foreground"}`}>
              {label}
            </span>
            {i < stepMeta.length - 1 && <span className="h-px flex-1 bg-border" />}
          </li>
        ))}
      </ol>

      {step === 1 && (
        <Card className="bg-gradient-card">
          <CardHeader>
            <CardTitle>Consent first</CardTitle>
            <CardDescription>
              Cloning works only for voices you own or have explicit permission to use. Every
              clone is logged and watermarked audio is detectable.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <FieldLabel className="text-xs text-muted-foreground">Consent language</FieldLabel>
              <select
                value={consentLang}
                onChange={(e) => setConsentLang(e.target.value)}
                className="rounded-md border bg-card px-2 py-1 text-sm"
                aria-label="Consent language"
              >
                <option value="en">English</option>
                <option value="bn">বাংলা</option>
                <option value="hi">हिन्दी</option>
              </select>
            </div>
            <blockquote className="rounded-lg border bg-card p-3 text-sm leading-relaxed">
              “{phrase}”
            </blockquote>
            <Field>
              <FieldLabel htmlFor="phrase">Type the phrase exactly</FieldLabel>
              <Input
                id="phrase"
                value={typedPhrase}
                onChange={(e) => setTypedPhrase(e.target.value)}
                placeholder={phrase}
              />
            </Field>
            <Field>
              <FieldLabel>Read the phrase aloud and record it</FieldLabel>
              <div className="flex items-center gap-3">
                {recording ? (
                  <Button variant="outline" onClick={stopConsentRecording}>
                    <Square data-icon="inline-start" />
                    Stop recording
                  </Button>
                ) : (
                  <Button variant="outline" onClick={() => void startConsentRecording()}>
                    <Mic data-icon="inline-start" />
                    {consentAudio ? "Re-record" : "Record"}
                  </Button>
                )}
                {consentAudio && (
                  <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
                    <CheckCircle2 className="size-4" /> Recorded
                  </span>
                )}
              </div>
              <FieldDescription>
                This recording is stored as proof of consent and encrypted at rest.
              </FieldDescription>
            </Field>
            <label className="flex items-start gap-2 text-sm">
              <Checkbox
                checked={consentGiven}
                onCheckedChange={(v) => setConsentGiven(v === true)}
                className="mt-0.5"
              />
              <span>
                I confirm this is <strong>my own voice</strong> or I have the owner&apos;s written
                permission, and I agree that cloned audio is watermarked and logged.
              </span>
            </label>
          </CardContent>
          <CardFooter className="justify-end">
            <Button onClick={nextFromConsent}>
              Continue
              <ArrowRight data-icon="inline-end" />
            </Button>
          </CardFooter>
        </Card>
      )}

      {step === 2 && (
        <Card className="bg-gradient-card">
          <CardHeader>
            <CardTitle>Voice sample</CardTitle>
            <CardDescription>
              10–30 seconds, quiet room, natural speaking pace.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <FieldLabel className="text-xs text-muted-foreground">Sample language</FieldLabel>
              <select
                value={sampleLang}
                onChange={(e) => setSampleLang(e.target.value)}
                className="rounded-md border bg-card px-2 py-1 text-sm"
                aria-label="Sample language"
              >
                {languages.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.native} · {l.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed p-6 text-center hover:bg-accent/40">
                <Upload className="size-5 text-muted-foreground" />
                <span className="text-sm font-medium">Upload a file</span>
                <span className="text-xs text-muted-foreground">WAV / MP3 / M4A, max 20 MB</span>
                <input
                  type="file"
                  accept="audio/*"
                  className="sr-only"
                  onChange={(e) => setSample(e.target.files?.[0] ?? null)}
                />
                {sample && (
                  <span className="text-xs text-foreground">
                    ✓ {sample.name} ({Math.round(sample.size / 1024)} KB)
                  </span>
                )}
              </label>
              <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed p-6 text-center">
                <Mic className="size-5 text-muted-foreground" />
                <span className="text-sm font-medium">Or record now</span>
                <span className="text-xs text-muted-foreground">
                  Talk naturally for 10–30 s about your day.
                </span>
                <MicButton
                  onTranscript={() => undefined}
                  disabled
                />
                <p className="text-xs text-muted-foreground">
                  Record in chat and upload it — studio-grade recording comes in the next release.
                </p>
              </div>
            </div>
          </CardContent>
          <CardFooter className="justify-between">
            <Button variant="ghost" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button onClick={nextFromSample} disabled={!sample}>
              Check quality
              <ArrowRight data-icon="inline-end" />
            </Button>
          </CardFooter>
        </Card>
      )}

      {step === 3 && (
        <Card className="bg-gradient-card">
          <CardHeader>
            <CardTitle>Quality check & finish</CardTitle>
            <CardDescription>
              We validate duration, loudness and clipping before submission.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <Alert>
              <CheckCircle2 />
              <AlertTitle>Ready to submit</AlertTitle>
              <AlertDescription>
                Sample: {sample?.name} ({sample ? Math.round(sample.size / 1024) : 0} KB) ·
                Consent recorded · Language: {sampleLang}
              </AlertDescription>
            </Alert>
            <Field>
              <FieldLabel htmlFor="vname">Name your voice</FieldLabel>
              <Input
                id="vname"
                value={voiceName}
                onChange={(e) => setVoiceName(e.target.value)}
                placeholder="Ayra (calm)"
              />
            </Field>
            <p className="text-xs text-muted-foreground">
              After submission the voice enters moderation. Once approved it appears under “My
              voices” and can be set as default. Deleting it removes the sample and embeddings
              permanently.
            </p>
          </CardContent>
          <CardFooter className="justify-between">
            <Button variant="ghost" onClick={() => setStep(2)}>
              Back
            </Button>
            <Button onClick={() => void submit()} disabled={busy}>
              {busy && <Spinner data-icon="inline-start" />}
              Submit voice
            </Button>
          </CardFooter>
        </Card>
      )}
    </div>
  );
}
