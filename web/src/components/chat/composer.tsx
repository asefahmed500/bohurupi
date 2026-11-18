"use client";

// Composer: text input + mic + send. Mic docked above the composer on phones.

import * as React from "react";
import { ArrowUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { InputGroup, InputGroupAddon, InputGroupTextarea } from "@/components/ui/input-group";
import { MicButton } from "./mic-button";

export function Composer({
  onSend,
  disabled,
  busy,
  voiceToVoice,
  placeholder = "Ask anything, in any language…",
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  busy?: boolean;
  voiceToVoice?: boolean;
  placeholder?: string;
}) {
  const [text, setText] = React.useState("");
  const areaRef = React.useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const t = text.trim();
    if (!t || busy) return;
    onSend(t);
    setText("");
    areaRef.current?.focus();
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-center md:hidden">
        <MicButton onTranscript={onSend} autoSend={voiceToVoice} disabled={disabled} />
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <InputGroup>
          <InputGroupTextarea
            ref={areaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            aria-label="Message"
          />
          <InputGroupAddon align="block-end">
            <span className="hidden md:inline-flex">
              <MicButton onTranscript={onSend} autoSend={voiceToVoice} disabled={disabled} />
            </span>
            <Button
              type="submit"
              size="icon-lg"
              className="ml-auto rounded-full"
              disabled={disabled || busy || !text.trim()}
              aria-label="Send message"
            >
              <ArrowUp />
            </Button>
          </InputGroupAddon>
        </InputGroup>
      </form>
    </div>
  );
}
