/** Client for Studio (/api/v1/artifacts): saved files, their versions and previews. */
import { ApiError, request } from "./api";

export type ArtifactVersion = {
  version: number;
  task_id: string | null;
  size: number | null;
  deleted: boolean;
  created_at: string;
};

export type Artifact = {
  id: string;
  path: string;
  media_type: string;
  conversation_id: string | null;
  /** The conversation's title, or the lone task's. */
  source_title: string | null;
  /** Set for a lone task's files. */
  task_id: string | null;
  versions: number;
  latest: ArtifactVersion;
  created_at: string;
  updated_at: string;
};

export type ArtifactDetail = { artifact: Artifact; versions: ArtifactVersion[] };

/** How the page shows a file: rendered, as text, or only offered for download. */
export type Viewer = "html" | "image" | "text" | "none";

export function viewerFor(mediaType: string): Viewer {
  const type = mediaType.split(";")[0]!.trim();
  if (type === "text/html") return "html";
  if (type.startsWith("image/")) return "image";
  if (
    type.startsWith("text/") ||
    ["application/json", "application/javascript", "application/xml"].includes(type)
  )
    return "text";
  return "none";
}

export const contentUrl = (id: string, version: number, download = false) =>
  `/api/v1/artifacts/${id}/versions/${version}/content${download ? "?download=true" : ""}`;

/** Where the file came from: its chat, or its task. */
export const sourceHref = (a: Artifact) =>
  a.conversation_id ? `/chat/${a.conversation_id}` : a.task_id ? `/tasks/${a.task_id}` : null;

export const studioApi = {
  list: () => request<Artifact[]>("/api/v1/artifacts?limit=500"),
  get: (id: string) => request<ArtifactDetail>(`/api/v1/artifacts/${id}`),
  preview: (id: string) =>
    request<{ url: string; expires_in: number }>(`/api/v1/artifacts/${id}/preview`, {
      method: "POST",
    }),
  /** A version's text, for showing source. Read with the session, like any API call. */
  text: async (id: string, version: number): Promise<string> => {
    const res = await fetch(contentUrl(id, version), { credentials: "same-origin" });
    if (!res.ok)
      throw new ApiError(res.status, "http_error", `Could not load the file (HTTP ${res.status}).`);
    return res.text();
  },
};
