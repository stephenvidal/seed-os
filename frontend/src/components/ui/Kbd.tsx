import type { ReactNode } from "react";
import { cn } from "./cn";

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[4px] border border-border bg-surface-2 px-1 font-sans text-2xs font-medium text-fg-subtle",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
