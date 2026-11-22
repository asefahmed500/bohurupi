"use client";

// Output language selector: Auto + the 20 launch languages.

import * as React from "react";
import { Languages } from "lucide-react";

import { useApp } from "@/lib/store";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Check } from "lucide-react";

export function LanguagePicker({
  value,
  onChange,
  trigger,
}: {
  value: string;
  onChange: (code: string) => void;
  trigger?: React.ReactElement;
}) {
  const { languages } = useApp();
  const current = languages.find((l) => l.code === value);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          trigger ?? (
            <Button variant="outline" size="sm">
              <Languages data-icon="inline-start" />
              Reply in: {value === "auto" ? "Auto" : (current?.native ?? value)}
            </Button>
          )
        }
      />
      <DropdownMenuContent align="end" className="max-h-80 overflow-y-auto">
        <DropdownMenuLabel>Reply language</DropdownMenuLabel>
        <DropdownMenuItem onClick={() => onChange("auto")}>
          <span className="flex-1">Auto — mirror the user</span>
          {value === "auto" && <Check className="size-4" />}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {languages.map((l) => (
          <DropdownMenuItem key={l.code} onClick={() => onChange(l.code)}>
            <span className="flex-1" dir="auto">
              {l.native} <span className="text-muted-foreground">· {l.name}</span>
            </span>
            {value === l.code && <Check className="size-4" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
