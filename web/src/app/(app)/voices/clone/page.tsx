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
import { blobToWavFile } from "@/lib/wav";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
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
import { PageContainer, PageHeader } from "@/components/page-container";

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
  const [recordingSample, setRecordingSample] = React.useState(false);
  const [sampleSeconds, setSampleSeconds] = React.useState(0);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const sampleRecorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<Blob[]>([]);
  const sampleChunksRef = React.useRef<Blob[]>([]);
  const sampleStreamRef = React.useRef<MediaStream | null>(null);
  const timerRef = React.useRef<number | null>(null);

  const stepMeta = ["Consent", "Sample", "Quality", "Finish"];

  const [phraseError, setPhraseError] = React.useState(false);

  const loadPhrase = React.useCallback(async (lang: string) => {
    setPhraseError(false);
    try {
      const res = await getConsentPhrase(lang);
      setPhrase(res.phrase);
    } catch {
      setPhrase("");
      setPhraseError(true);
    }
  }, []);

  React.useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadPhrase(consentLang);
  }, [consentLang, loadPhrase]);

  React.useEffect(() => {
    if (user) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setVoiceName((n) => n || `${user.name || "My"}'s voice`);
    }
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
      sampleStreamRef.current?.getTracks().forEach((t) => t.stop());
    };
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

  const startSampleRecording = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true }).catch(() => null);
    if (!stream) {
      toast.error("Microphone access denied");
      return;
    }
    sampleStreamRef.current = stream;
    const recorder = new MediaRecorder(stream);
    sampleChunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) sampleChunksRef.current.push(e.data);
    };
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(sampleChunksRef.current, { type: recorder.mimeType || "audio/webm" });
      try {
        const wav = await blobToWavFile(blob, "voice-sample");
        setSample(wav);
        toast.success(`Sample recorded (${Math.round(wav.size / 1024)} KB)`);
      } catch {
        toast.error("Could not process the recording — try uploading a file instead");
      }
    };
    recorder.start();
    sampleRecorderRef.current = recorder;
    setRecordingSample(true);
    setSampleSeconds(0);
    timerRef.current = window.setInterval(() => {
      setSampleSeconds((s) => {
        // hard-stop at 35 s — samples over 30 s are rejected server-side
        if (s + 1 >= 35) {
          window.clearInterval(timerRef.current!);
          timerRef.current = null;
          sampleRecorderRef.current?.stop();
          sampleRecorderRef.current = null;
          setRecordingSample(false);
          toast.info("Recording stopped at 35 s (30 s max for a sample)");
        }
        return Math.min(60, s + 1);
      });
    }, 1000);
  };

  const stopSampleRecording = () => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    sampleRecorderRef.current?.stop();
    sampleRecorderRef.current = null;
    setRecordingSample(false);
  };

  const nextFromConsent = () => {
    if (!consentGiven) {
      toast.error("Please confirm you have the right to clone this voice");
      return;
    }
    if (phraseError) {
      toast.error("The consent phrase could not be loaded — retry first");
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
      // the backend reads uploads with libsndfile — always send WAV
      const sampleWav =
        sample.type === "audio/wav" ? sample : await blobToWavFile(sample, sample.name || "sample");
      const consentWav =
        consentAudio.type === "audio/wav"
          ? consentAudio
          : await blobToWavFile(consentAudio, "consent");
      const res = await cloneVoice(
        {
          name: voiceName.trim() || "My voice",
          consent: String(consentGiven),
          consent_lang: consentLang,
          consent_phrase_text: typedPhrase.trim(),
          sample_lang: sampleLang,
        },
        sampleWav,
        consentWav
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
    <PageContainer size="narrow">
      <Link href="/voices" className={buttonVariants({ variant: "ghost", size: "sm" })}>
        <ArrowLeft data-icon="inline-start" />
        Voice library
      </Link>

      <PageHeader
        title="Clone a voice"
        description="Consent → sample → quality check → finish. Cloned audio is watermarked and logged."
      />

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
            {phraseError ? (
              <div className="flex items-center justify-between gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm">
                <span>Could not load the consent phrase.</span>
                <Button size="sm" variant="outline" onClick={() => void loadPhrase(consentLang)}>
                  Retry
                </Button>
              </div>
            ) : (
              <blockquote className="rounded-lg border bg-card p-3 text-sm leading-relaxed">
                “{phrase}”
              </blockquote>
            )}
            <Field>
              <FieldLabel htmlFor="phrase">Type the phrase exactly</FieldLabel>
              <Input
                id="phrase"
                value={typedPhrase}
                onChange={(e) => setTypedPhrase(e.target.value)}
                placeholder={phrase}
                disabled={phraseError}
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
                  onChange={(e) => {
                    const file = e.target.files?.[0] ?? null;
                    if (file && file.size > 20 * 1024 * 1024) {
                      toast.error("File is over 20 MB — trim it and try again");
                      return;
                    }
                    setSample(file);
                  }}
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
                {recordingSample ? (
                  <Button variant="outline" onClick={stopSampleRecording}>
                    <Square data-icon="inline-start" />
                    Stop ({sampleSeconds}s)
                  </Button>
                ) : (
                  <Button variant="outline" onClick={() => void startSampleRecording()}>
                    <Mic data-icon="inline-start" />
                    {sample ? "Re-record" : "Record sample"}
                  </Button>
                )}
                {sample && !recordingSample && (
                  <span className="inline-flex items-center gap-1 text-xs text-foreground">
                    <CheckCircle2 className="size-4" /> {sample.name} (
                    {Math.round(sample.size / 1024)} KB)
                  </span>
                )}
                {recordingSample && sampleSeconds < 10 && (
                  <p className="text-xs text-muted-foreground">Keep talking — at least 10 s.</p>
                )}
              </div>
            </div>
          </CardContent>
          <CardFooter className="justify-between">
            <Button variant="ghost" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button onClick={nextFromSample} disabled={!sample}>
              Continue
              <ArrowRight data-icon="inline-end" />
            </Button>
          </CardFooter>
        </Card>
      )}

      {step === 3 && (
        <Card className="bg-gradient-card">
          <CardHeader>
            <CardTitle>Name &amp; submit</CardTitle>
            <CardDescription>
              Duration, loudness and clipping are validated on the server when you submit.
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
            <Button onClick={() => void submit()} loading={busy}>
              Submit voice
            </Button>
          </CardFooter>
        </Card>
      )}
    </PageContainer>
  );
}
