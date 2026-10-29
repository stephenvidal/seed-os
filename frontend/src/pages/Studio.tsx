import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Boxes, Download } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { Failure, Loading, Viewer } from "../components/studio/ArtifactViewer";
import { ApiError } from "../lib/api";
import { formatBytes } from "../lib/format";
import { contentUrl, sourceHref, studioApi } from "../lib/studio";
import type { Artifact } from "../lib/studio";

const when = (iso: string) => new Date(iso).toLocaleString();

/** Artifacts grouped by the chat or task that made them, most recent first. */
function groups(artifacts: Artifact[]) {
  const out = new Map<string, { title: string; href: string | null; items: Artifact[] }>();
  for (const a of artifacts) {
    const key = a.conversation_id ?? a.task_id ?? a.id;
    const g = out.get(key) ?? {
      title: a.source_title ?? "Untitled",
      href: sourceHref(a),
      items: [],
    };
    g.items.push(a);
    out.set(key, g);
  }
  return [...out.values()];
}

export function StudioPage() {
  const list = useQuery({ queryKey: ["artifacts"], queryFn: studioApi.list, retry: false });
  return (
    <>
      <PageHeader
        title="Studio"
        description="Every file your chats and tasks made, with each saved version."
      />
      {list.isPending ? (
        <Panel>
          <Loading />
        </Panel>
      ) : list.isError ? (
        <Panel>
          <Failure error={list.error} />
        </Panel>
      ) : list.data.length === 0 ? (
        <Panel>
          <EmptyState icon={Boxes} title="No saved files yet">
            Each file an answer creates or changes is saved here after it finishes, with a version
            for every change. Ask Chat to make something.
          </EmptyState>
        </Panel>
      ) : (
        <div className="flex flex-col gap-4">
          {groups(list.data).map((g) => (
            <Panel
              key={g.href ?? g.title}
              title={g.title}
              action={
                g.href && (
                  <Link to={g.href} className="text-xs text-accent hover:underline">
                    {g.href.startsWith("/chat") ? "Open chat" : "Open task"}
                  </Link>
                )
              }
            >
              <ul className="divide-y divide-border">
                {g.items.map((a) => (
                  <li key={a.id}>
                    <Link
                      to={`/studio/${a.id}`}
                      className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-2"
                    >
                      <span className="min-w-0 flex-1 truncate font-mono text-sm text-fg">
                        {a.path}
                      </span>
                      {a.latest.deleted && <Badge tone="warning">deleted</Badge>}
                      <span className="shrink-0 text-xs text-fg-muted tabular-nums">
                        {a.versions === 1 ? "1 version" : `${a.versions} versions`} ·{" "}
                        {formatBytes(a.latest.size)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Panel>
          ))}
        </div>
      )}
    </>
  );
}

export function StudioArtifactPage() {
  const { id = "" } = useParams();
  const detail = useQuery({
    queryKey: ["artifact", id],
    queryFn: () => studioApi.get(id),
    retry: false,
  });
  const [picked, setPicked] = useState<number | null>(null);

  const back = (
    <Link
      to="/studio"
      className="mb-3 inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg"
    >
      <ArrowLeft size={13} aria-hidden /> Studio
    </Link>
  );
  if (detail.isPending)
    return (
      <>
        {back}
        <Loading />
      </>
    );
  if (detail.isError)
    return (
      <>
        {back}
        <Panel>
          {detail.error instanceof ApiError && detail.error.code === "not_found" ? (
            <EmptyState icon={Boxes} title="No such file">
              It may have been deleted with its conversation.
            </EmptyState>
          ) : (
            <Failure error={detail.error} />
          )}
        </Panel>
      </>
    );

  const { artifact: a, versions } = detail.data;
  const shown = versions.find((v) => v.version === picked) ?? versions[0]!;
  const href = sourceHref(a);
  return (
    <>
      {back}
      <PageHeader
        title={a.path}
        description={a.source_title ? `From “${a.source_title}”` : undefined}
        actions={
          <>
            {href && (
              <Link to={href} className="text-xs text-accent underline-offset-2 hover:underline">
                {a.conversation_id ? "Open chat" : "Open task"}
              </Link>
            )}
            {!shown.deleted && (
              <a
                href={contentUrl(a.id, shown.version, true)}
                download
                className="inline-flex h-7 items-center gap-1.5 rounded-control border border-border bg-surface-1 px-2.5 text-xs font-medium text-fg hover:bg-surface-2"
              >
                <Download size={13} aria-hidden /> Download v{shown.version}
              </a>
            )}
          </>
        }
      />
      <div className="flex min-w-0 flex-col gap-4">
        <Panel title={`Version ${shown.version}${shown.deleted ? " (deleted)" : ""}`}>
          <Viewer artifact={a} v={shown} />
        </Panel>
        <Panel title="Versions">
          <div className="relative overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-fg-muted">
                <tr>
                  {["Version", "Saved", "Size", "Made by"].map((h) => (
                    <th key={h} className="px-4 py-2 font-medium whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                  <th className="px-4 py-2">
                    <span className="sr-only">Show</span>
                  </th>
                </tr>
              </thead>
              <tbody className="tabular-nums text-fg">
                {versions.map((v) => (
                  <tr
                    key={v.version}
                    className={v.version === shown.version ? "bg-surface-2" : undefined}
                  >
                    <td className="border-t border-border px-4 py-1.5 font-mono">
                      v{v.version}
                      {v.deleted && " · deleted"}
                    </td>
                    <td className="border-t border-border px-4 py-1.5 whitespace-nowrap">
                      {when(v.created_at)}
                    </td>
                    <td className="border-t border-border px-4 py-1.5 whitespace-nowrap">
                      {formatBytes(v.size)}
                    </td>
                    <td className="border-t border-border px-4 py-1.5">
                      {v.task_id ? (
                        <Link
                          to={`/inspector/${v.task_id}`}
                          className="text-accent hover:underline"
                        >
                          Inspect run
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="border-t border-border px-4 py-1.5 text-right">
                      {v.version !== shown.version && (
                        <Button size="sm" variant="ghost" onClick={() => setPicked(v.version)}>
                          Show v{v.version}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </>
  );
}
