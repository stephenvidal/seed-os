import { useQuery } from "@tanstack/react-query";
import { Boxes } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { tasksApi } from "../../lib/tasks";
import { savedFiles, studioApi } from "../../lib/studio";
import { Modal } from "../ui/Modal";
import { Failure, Loading, Viewer } from "./ArtifactViewer";

/** A saved file, open over the chat: the same viewer Studio uses. */
function ArtifactModal({
  id,
  version,
  onClose,
}: {
  id: string;
  version: number;
  onClose: () => void;
}) {
  const detail = useQuery({
    queryKey: ["artifact", id],
    queryFn: () => studioApi.get(id),
    retry: false,
  });
  const a = detail.data?.artifact;
  const shown =
    detail.data?.versions.find((v) => v.version === version) ?? detail.data?.versions[0];
  return (
    <Modal
      title={a?.path ?? "Saved file"}
      onClose={onClose}
      actions={
        a && (
          <Link to={`/studio/${a.id}`} className="text-xs text-accent hover:underline">
            Open in Studio
          </Link>
        )
      }
    >
      {detail.isPending ? (
        <Loading />
      ) : detail.isError ? (
        <Failure
          error={
            detail.error instanceof ApiError && detail.error.code === "not_found"
              ? new Error("This file no longer exists.")
              : detail.error
          }
        />
      ) : (
        a && shown && <Viewer artifact={a} v={shown} />
      )}
    </Modal>
  );
}

/**
 * Links under a finished answer to the files it saved to Studio. Looks only when the
 * chat has saved files at all, so a chat without any costs one request.
 */
export function ArtifactLinks({
  conversationId,
  taskId,
  enabled,
}: {
  conversationId: string;
  taskId: string;
  enabled: boolean;
}) {
  const files = useQuery({
    queryKey: ["artifacts", "conversation", conversationId],
    queryFn: () => studioApi.inConversation(conversationId),
    enabled,
    retry: false,
    // A turn that just finished may have saved files the cached list predates.
    staleTime: 0,
  });
  const events = useQuery({
    queryKey: ["task-all-events", taskId],
    queryFn: () => tasksApi.allEvents(taskId),
    enabled: enabled && !!files.data?.length,
    retry: false,
    staleTime: Infinity,
  });
  const [open, setOpen] = useState<{ id: string; version: number } | null>(null);
  const byPath = new Map((files.data ?? []).map((a) => [a.path, a]));
  const links = savedFiles(events.data ?? []).flatMap((s) => {
    const a = byPath.get(s.path);
    return a ? [{ a, version: s.version }] : [];
  });
  if (!links.length) return null;
  return (
    <>
      <ul aria-label="Files saved to Studio" className="flex flex-wrap gap-2">
        {links.map(({ a, version }) => (
          <li key={a.id}>
            <button
              type="button"
              onClick={() => setOpen({ id: a.id, version })}
              className="inline-flex max-w-full items-center gap-1.5 rounded-control border border-border bg-surface-1 px-2.5 py-1 font-mono text-xs text-fg hover:bg-surface-2"
            >
              <Boxes size={13} className="shrink-0 text-accent" aria-hidden />
              <span className="truncate">{a.path}</span>
            </button>
          </li>
        ))}
      </ul>
      {open && <ArtifactModal {...open} onClose={() => setOpen(null)} />}
    </>
  );
}
