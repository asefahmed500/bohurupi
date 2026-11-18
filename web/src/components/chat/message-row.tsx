"use client";

// Message row: bubble + audio bar + translation toggle + change-voice pill.

import * as React from "react";
import { AudioLines, Languages } from "lucide-react";

import { useApp } from "@/lib/store";
import type { AudioAsset, ChatMessage, Voice } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Message, MessageContent } from "@/components/ui/message";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Spinner } from "@/components/ui/spinner";
import { AudioBar } from "./audio-bar";
import { VoicePicker } from "./voice-picker";

export function MessageRow({
  message,
  onRespeak,
  respeaking,
  generating,
  spokenWith,
  fallback,
}: {
  message: ChatMessage;
  onRespeak?: (voice: Voice) => void;
  respeaking?: boolean;
  generating?: boolean;
  spokenWith?: string;
  fallback?: boolean;
}) {
  const { languages, settings } = useApp();
  const [showTranslation, setShowTranslation] = React.useState(false);
  const isUser = message.role === "user";
  const lang = languages.find((l) => l.code === message.lang);
  const rtl = lang?.rtl ?? false;
  const translation = showTranslation && message.translations ? Object.values(message.translations)[0] : null;
  const primaryAudio: AudioAsset | undefined = message.audio?.[message.audio.length - 1];
  const chunks = message.pcm && message.pcm.length > 0 ? message.pcm : undefined;

  return (
    <Message align={isUser ? "end" : "start"}>
      <MessageContent>
        <Bubble variant={isUser ? "default" : "outline"} align={isUser ? "end" : "start"}>
          <BubbleContent>
            <p dir={rtl ? "rtl" : "ltr"} className="whitespace-pre-wrap">
              {translation ?? message.text}
              {generating && !message.text && (
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  <Spinner className="size-3" /> Preparing voice…
                </span>
              )}
            </p>
            {generating && message.text && (
              <span aria-hidden className="shimmer mt-1 block h-3 w-24 rounded-full" />
            )}
          </BubbleContent>
        </Bubble>

        {!isUser && (primaryAudio || chunks || generating) && (
          <AudioBar
            asset={primaryAudio}
            chunks={chunks}
            generating={generating && !chunks}
          />
        )}

        {!isUser && (
          <div className="flex flex-wrap items-center gap-1.5 px-1 text-xs text-muted-foreground">
            {message.lang && <Badge variant="secondary">{lang?.native ?? message.lang}</Badge>}
            {spokenWith && (
              <Badge variant={fallback ? "destructive" : "secondary"}>
                <AudioLines data-icon="inline-start" />
                {fallback ? `Spoken with ${spokenWith} (fallback)` : spokenWith}
              </Badge>
            )}
            {message.translations && Object.keys(message.translations).length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 rounded-full px-2 text-xs"
                onClick={() => setShowTranslation((v) => !v)}
              >
                <Languages data-icon="inline-start" />
                {showTranslation ? "Hide translation" : "Translation"}
              </Button>
            )}
            {onRespeak && !generating && (
              <VoicePicker
                value=""
                onChange={(v) => onRespeak(v)}
                title="Re-speak with another voice"
                trigger={
                  <Button variant="ghost" size="sm" className="h-6 rounded-full px-2 text-xs">
                    <AudioLines data-icon="inline-start" />
                    Change voice
                  </Button>
                }
              />
            )}
            {respeaking && (
              <span className="inline-flex items-center gap-1">
                <Spinner className="size-3" /> Re-speaking…
              </span>
            )}
            {settings.captions && generating && (
              <span className="sr-only" role="status">
                Generating voice
              </span>
            )}
          </div>
        )}
      </MessageContent>
    </Message>
  );
}
