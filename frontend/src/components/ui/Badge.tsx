import type { ReactNode } from "react";
import { cn } from "./cn";

type Tone = "neutral" | "accent" | "warning" | "danger";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-3 text-fg-muted",
  accent: "bg-accent-soft text-accent-soft-fg",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-full px-2 text-2xs font-medium",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}
