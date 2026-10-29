import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "../ui/Button";
import { Markdown } from "../ui/Markdown";
import { HtmlFrame, SourceView, ViewSwitch } from "../ui/Rendered";
import type { ViewMode } from "../ui/Rendered";
import { Spinner } from "../ui/Spinner";
import { contentUrl, studioApi, viewerFor } from "../../lib/studio";
import type { Artifact, ArtifactVersion } from "../../lib/studio";

/** Longest text shown inline; the rest is a download away. */
const MAX_TEXT_CHARS = 200_000;

export function Failure({ error }: { error: Error }) {
  return (
    <div className="flex items-start gap-2 px-4 py-4 text-sm text-danger" role="alert">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden /> {error.message}
    </div>
  );
}

export function Loading() {
  return (
    <div className="flex items-center gap-2 px-4 py-6 text-sm text-fg-muted">
      <Spinner /> Loading…
    </div>
  );
}

function TextView({ id, version }: { id: string; version: number }) {
  const text = useText(id, version);
  if (text.isPending) return <Loading />;
  if (text.isError) return <Failure error={text.error} />;
  const cut = text.data.length > MAX_TEXT_CHARS;
  return (
    <>
      <SourceView
        text={cut ? text.data.slice(0, MAX_TEXT_CHARS) : text.data}
        className="px-4 py-3 whitespace-pre"
      />
      {cut && (
        <p className="border-t border-border px-4 py-2 text-xs text-fg-muted">
          Showing the first {MAX_TEXT_CHARS.toLocaleString()} characters. Download it for the rest.
        </p>
      )}
    </>
  );
}

const useText = (id: string, version: number) =>
  useQuery({
    queryKey: ["artifact-text", id, version],
    queryFn: () => studioApi.text(id, version),
    retry: false,
    staleTime: Infinity, // a saved version never changes
  });

/** The preview starts as soon as the page opens; it is the first view of an HTML file. */
function HtmlPreview({ artifact }: { artifact: Artifact }) {
  const preview = useMutation({ mutationFn: () => studioApi.preview(artifact.id) });
  const { mutate } = preview;
  useEffect(() => mutate(), [mutate]);
  if (preview.data)
    return (
      <div className="px-4 py-3">
        <HtmlFrame
          title={`Preview of ${artifact.path}`}
          // Served by the API with its own policy: scripts run in an opaque origin, apart
          // from SEED, with no network access.
          src={preview.data.url}
        />
      </div>
    );
  if (preview.isError)
    return (
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <Failure error={preview.error} />
        <Button size="sm" onClick={() => mutate()}>
          <Play size={13} aria-hidden /> Run preview
        </Button>
      </div>
    );
  return <Loading />;
}

/** Markdown files render as formatted text; their source is one switch away. */
function MarkdownFile({ id, version }: { id: string; version: number }) {
  const text = useText(id, version);
  if (text.isPending) return <Loading />;
  if (text.isError) return <Failure error={text.error} />;
  const cut = text.data.length > MAX_TEXT_CHARS;
  return (
    <div className="px-4 py-3">
      <Markdown text={cut ? text.data.slice(0, MAX_TEXT_CHARS) : text.data} />
    </div>
  );
}

/** One saved version of a file, shown the way Studio shows it. */
export function Viewer({ artifact, v }: { artifact: Artifact; v: ArtifactVersion }) {
  const [mode, setMode] = useState<ViewMode>("rendered");
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
  // Rendered first when there is a rendered view of this version. A preview runs the
  // latest saved files, so an older HTML version only has its source.
  const rendered = kind === "markdown" || (kind === "html" && latest);
  const shown = rendered ? mode : "source";
  return (
    <>
      {rendered && (
        <div className="flex justify-end border-b border-border px-4 py-1.5">
          <ViewSwitch value={mode} onChange={setMode} />
        </div>
      )}
      {kind === "html" && !latest && (
        <p className="px-4 pt-3 text-xs text-fg-muted">
          Previews run the latest version. This is version {v.version}&apos;s source.
        </p>
      )}
      {shown === "source" && <TextView id={artifact.id} version={v.version} />}
      {shown === "rendered" && kind === "html" && (
        <HtmlPreview key={artifact.id} artifact={artifact} />
      )}
      {shown === "rendered" && kind === "markdown" && (
        <MarkdownFile id={artifact.id} version={v.version} />
      )}
    </>
  );
}
