"use client";

// MicButton: hold-or-toggle recording with visual states
// idle → listening (pulsing) → processing → transcript confirm.

import * as React from "react";
import { Loader2, Mic, Send, Square } from "lucide-react";
import { toast } from "sonner";

import { transcribe } from "@/lib/api";
import { Button } from "@/components/ui/button";

export type MicState = "idle" | "listening" | "processing" | "confirm";

export function MicButton({
  onTranscript,
  autoSend = false,
  disabled,
}: {
  onTranscript: (text: string) => void;
  /** voice-to-voice: send the transcript immediately after recognition */
  autoSend?: boolean;
  disabled?: boolean;
}) {
  const [state, setState] = React.useState<MicState>("idle");
  const [transcript, setTranscript] = React.useState("");
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<Blob[]>([]);
  const streamRef = React.useRef<MediaStream | null>(null);

  const cleanup = React.useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  React.useEffect(() => cleanup, [cleanup]);

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        setState("processing");
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        cleanup();
        if (blob.size < 1024) {
          toast.error("Recording was too short");
          setState("idle");
          return;
        }
        try {
          const result = await transcribe(blob);
          if (!result.text.trim()) {
            toast.error("No speech detected");
            setState("idle");
            return;
          }
          if (autoSend) {
            onTranscript(result.text.trim());
            setState("idle");
          } else {
            setTranscript(result.text.trim());
            setState("confirm");
          }
        } catch (e) {
          toast.error(e instanceof Error ? e.message : "Speech recognition failed");
          setState("idle");
        }
      };
      recorder.start();
      recorderRef.current = recorder;
      setState("listening");
    } catch {
      toast.error("Microphone access denied. Allow mic access in your browser.");
    }
  };

  const stopRecording = React.useCallback(() => {
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
    }
  }, []);

  const toggle = () => {
    if (state === "idle" || state === "confirm") {
      setTranscript("");
      void start();
    } else if (state === "listening") {
      stopRecording();
    }
  };

  if (state === "confirm") {
    return (
      <div className="flex items-center gap-2 rounded-md border bg-card py-1 pr-1 pl-3">
        <p
          className="line-clamp-2 max-w-40 text-xs text-muted-foreground sm:max-w-64"
          role="status"
          title={transcript}
        >
          {transcript}
        </p>
        <Button
          size="icon-sm"
          className="rounded-md"
          aria-label="Send transcript"
          autoFocus
          onClick={() => {
            onTranscript(transcript);
            setState("idle");
            setTranscript("");
          }}
        >
          <Send />
        </Button>
        <Button
          size="icon-sm"
          variant="ghost"
          className="rounded-md"
          aria-label="Discard transcript"
          onClick={() => {
            setState("idle");
            setTranscript("");
          }}
        >
          <Square />
        </Button>
      </div>
    );
  }

  return (
    <Button
      size="icon-lg"
      onClick={toggle}
      disabled={disabled || state === "processing"}
      aria-label={
        state === "listening"
          ? "Recording — activate to stop"
          : state === "processing"
            ? "Processing speech"
            : "Record speech"
      }
      aria-pressed={state === "listening"}
      className={`rounded-md ${state === "listening" ? "mic-pulse" : ""}`}
    >
      {state === "processing" ? <Loader2 className="animate-spin" /> : <Mic />}
    </Button>
  );
}
