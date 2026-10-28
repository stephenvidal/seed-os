import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Honest empty state. Used where a capability is not built yet: it says so and
 * names the milestone that delivers it, rather than rendering fake data.
 */
export function EmptyState({
  icon: Icon,
  title,
  children,
  milestone,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
  milestone?: string;
}) {
  return (
    <div className="flex flex-col items-start gap-3 px-5 py-8 sm:px-6">
      <div className="grid h-9 w-9 place-items-center rounded-control border border-border bg-surface-2 text-fg-muted">
        <Icon size={16} strokeWidth={1.75} aria-hidden />
      </div>
      <div>
        <p className="text-sm font-medium text-fg">{title}</p>
        <div className="mt-1 max-w-md text-sm text-fg-muted">{children}</div>
      </div>
      {milestone && (
        <p className="font-mono text-2xs uppercase tracking-wider text-fg-subtle">
          Arrives in {milestone}
        </p>
      )}
    </div>
  );
}
