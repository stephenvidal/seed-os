import type { ReactNode } from "react";
import { cn } from "./cn";

export function Panel({
  title,
  action,
  children,
  className,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn("rounded-panel border border-border bg-surface-1", className)}
      aria-label={typeof title === "string" ? title : undefined}
    >
      {title && (
        <header className="flex h-10 items-center justify-between border-b border-border px-4">
          <h2 className="text-xs font-semibold text-fg">{title}</h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
