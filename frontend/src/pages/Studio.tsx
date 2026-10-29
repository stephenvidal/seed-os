import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Boxes, Download, Play } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Panel } from "../components/ui/Panel";
import { Spinner } from "../components/ui/Spinner";
import { ApiError } from "../lib/api";
import { formatBytes } from "../lib/format";
import { contentUrl, sourceHref, studioApi, viewerFor } from "../lib/studio";
import type { Artifact, ArtifactVersion } from "../lib/studio";

/** Longest text shown inline; the rest is a download away. */
const MAX_TEXT_CHARS = 200_000;
const when = (iso: string) => new Date(iso).toLocaleString();

function Failure({ error }: { error: Error }) {
  return (
    <div className="flex items-start gap-2 px-4 py-4 text-sm text-danger" role="alert">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden /> {error.message}
    </div>
  );
}

function Loading() {
  return (
    <div className="flex items-center gap-2 px-4 py-6 text-sm text-fg-muted">
      <Spinner /> Loading…
    </div>
  );
}

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

function TextView({ id, version }: { id: string; version: number }) {
  const text = useQuery({
    queryKey: ["artifact-text", id, version],
    queryFn: () => studioApi.text(id, version),
    retry: false,
    staleTime: Infinity, // a saved version never changes
  });
  if (text.isPending) return <Loading />;
  if (text.isError) return <Failure error={text.error} />;
  const cut = text.data.length > MAX_TEXT_CHARS;
  return (
    <>
      <pre className="max-h-[32rem] overflow-auto px-4 py-3 font-mono text-xs leading-relaxed text-fg">
        {cut ? text.data.slice(0, MAX_TEXT_CHARS) : text.data}
      </pre>
      {cut && (
        <p className="border-t border-border px-4 py-2 text-xs text-fg-muted">
          Showing the first {MAX_TEXT_CHARS.toLocaleString()} characters. Download it for the rest.
        </p>
      )}
    </>
  );
}

function HtmlPreview({ artifact }: { artifact: Artifact }) {
  const preview = useMutation({ mutationFn: () => studioApi.preview(artifact.id) });
  if (preview.data)
    return (
      <iframe
        title={`Preview of ${artifact.path}`}
        src={preview.data.url}
        // No allow-same-origin: the page runs in an opaque origin, apart from SEED.
        sandbox="allow-scripts allow-modals"
        className="h-[32rem] w-full border-0 bg-white"
      />
    );
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3">
      <Button size="sm" onClick={() => preview.mutate()} disabled={preview.isPending}>
        <Play size={13} aria-hidden /> Run preview
      </Button>
      <p className="text-xs text-fg-muted">
        Runs the latest saved files in a sandbox with no network access and no access to your SEED
        session.
      </p>
      {preview.isError && <Failure error={preview.error} />}
    </div>
  );
}

function Viewer({ artifact, v }: { artifact: Artifact; v: ArtifactVersion }) {
  if (v.deleted)
    return <p className="px-4 py-3 text-sm text-fg-muted">The file was deleted in this version.</p>;
  const kind = viewerFor(artifact.media_type);
  const latest = v.version === artifact.latest.version;
  if (kind === "image")
    return (
      <div className="px-4 py-3">
        <img
          src={contentUrl(artifact.id, v.version)}
          alt={`${artifact.path}, version ${v.version}`}
          className="max-h-[32rem] max-w-full"
        />
      </div>
    );
  if (kind === "none")
    return (
      <p className="px-4 py-3 text-sm text-fg-muted">
        No preview for this kind of file ({artifact.media_type.split(";")[0]}). Download it to open
        it.
      </p>
    );
  return (
    <>
      {kind === "html" && latest && <HtmlPreview key={artifact.id} artifact={artifact} />}
      {kind === "html" && !latest && (
        <p className="px-4 pt-3 text-xs text-fg-muted">
          Previews run the latest version. This is version {v.version}&apos;s source.
        </p>
      )}
      <TextView id={artifact.id} version={v.version} />
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
