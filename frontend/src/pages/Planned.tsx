import { Circle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";

export type PlannedPageProps = {
  title: string;
  description: string;
  icon: LucideIcon;
  emptyTitle: string;
  emptyBody: string;
  milestone: string;
  scope: string[];
};

/**
 * A workspace area whose backend is not built yet. It shows an honest empty state
 * and the ratified scope (docs/requirements.md) — no controls that do nothing.
 */
export function PlannedPage({
  title,
  description,
  icon,
  emptyTitle,
  emptyBody,
  milestone,
  scope,
}: PlannedPageProps) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Panel>
          <EmptyState icon={icon} title={emptyTitle} milestone={milestone}>
            {emptyBody}
          </EmptyState>
        </Panel>
        <Panel title="Planned scope">
          <ul className="flex flex-col gap-2 px-4 py-3">
            {scope.map((s) => (
              <li key={s} className="flex items-start gap-2 text-sm text-fg-muted">
                <Circle
                  size={6}
                  className="mt-[7px] shrink-0 fill-fg-subtle text-fg-subtle"
                  aria-hidden
                />
                {s}
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </>
  );
}
