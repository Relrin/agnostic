// Artefacts: the files a session's runs produced. The list comes from agnostic-bridge on the instance
// (`/agnostic/v1/artifacts`, read through the gateway as the person); the bytes come from the control plane's
// artefact route, which serves them with an isolating policy, so previews never run on the app's own origin.
import { apiUrl, gatewayJson, jsonBody } from "@agnostic/api";
import { skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { STALE_TIME } from "../query";

export type ArtifactKind = "image" | "audio" | "video" | "file";

/** One stored artefact, as the bridge lists it. */
export type Artifact = {
  id: string;
  storage_key: string;
  session_id: string;
  run_id?: string | null;
  component_kind?: "agent" | "team" | "workflow" | null;
  component_id?: string | null;
  kind: ArtifactKind;
  filename: string;
  title: string;
  content_type: string;
  size?: number | null;
  sha256?: string | null;
  path?: string | null;
  source?: string | null;
  producer?: string | null;
  revision: number;
  role: "output" | "input";
  created_at?: string | null;
};

export type ArtifactList = { data: Artifact[]; scanned_sessions: number };

/** How the viewer shows a file. */
export type ViewerKind =
  | "markdown"
  | "html"
  | "svg"
  | "image"
  | "pdf"
  | "csv"
  | "json"
  | "code"
  | "text"
  | "audio"
  | "video"
  | "binary";

const CODE_LANGUAGES: Record<string, string> = {
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  mjs: "javascript",
  jsx: "jsx",
  css: "css",
  sql: "sql",
  sh: "bash",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  rs: "rust",
  go: "go",
  java: "java",
  rb: "ruby",
  xml: "xml",
};

export function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(dot + 1).toLowerCase() : "";
}

export function codeLanguage(filename: string): string | undefined {
  return CODE_LANGUAGES[extensionOf(filename)];
}

export function viewerKind(contentType: string, filename: string): ViewerKind {
  const type = contentType.split(";")[0]?.trim().toLowerCase() ?? "";
  const extension = extensionOf(filename);
  if (type === "text/markdown" || extension === "md" || extension === "markdown") return "markdown";
  if (type === "text/html" || type === "application/xhtml+xml") return "html";
  if (type === "image/svg+xml") return "svg";
  if (type.startsWith("image/")) return "image";
  if (type === "application/pdf") return "pdf";
  if (type === "text/csv" || extension === "csv") return "csv";
  if (type.includes("json") || extension === "json") return "json";
  if (type.startsWith("audio/")) return "audio";
  if (type.startsWith("video/")) return "video";
  if (codeLanguage(filename)) return "code";
  if (type.startsWith("text/")) return "text";
  return "binary";
}

const artifactKeys = {
  session: (instance: string, sessionId: string) =>
    [instance, "agentos", "artifacts", "session", sessionId] as const,
  recent: (instance: string, filters: RecentFilters) =>
    [instance, "agentos", "artifacts", "recent", filters] as const,
  all: (instance: string) => [instance, "agentos", "artifacts"] as const,
};

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== "") search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** The session's artefacts (outputs only), newest run first. */
export function useSessionArtifacts(
  instance: string | undefined,
  sessionId: string | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: artifactKeys.session(instance ?? "", sessionId ?? ""),
    queryFn:
      instance && sessionId && enabled
        ? () =>
            gatewayJson<ArtifactList>(
              instance,
              `agnostic/v1/artifacts${query({ session_id: sessionId })}`,
            ).then((body) => body.data)
        : skipToken,
    staleTime: STALE_TIME.live,
    retry: false,
  });
}

export type RecentFilters = {
  componentId?: string | undefined;
  kind?: ArtifactKind | undefined;
  sessions?: number;
};

/** Artefacts of the most recently updated sessions on the instance. */
export function useRecentArtifacts(instance: string | undefined, filters: RecentFilters) {
  return useQuery({
    queryKey: artifactKeys.recent(instance ?? "", filters),
    queryFn: instance
      ? () =>
          gatewayJson<ArtifactList>(
            instance,
            `agnostic/v1/artifacts/recent${query({
              sessions: filters.sessions ?? 50,
              component_id: filters.componentId,
              kind: filters.kind,
            })}`,
          )
      : skipToken,
    staleTime: STALE_TIME.live,
    retry: false,
  });
}

/**
 * After a run settles: collect from sandbox checkpoints (a no-op unless the component is a sandboxed harness), then
 * refresh the session's list so the new files show up.
 */
export function useRefreshArtifacts(instance: string | undefined) {
  const client = useQueryClient();
  return useCallback(
    async (sessionId: string | undefined) => {
      if (!instance || !sessionId) return;
      try {
        await gatewayJson(instance, "agnostic/v1/artifacts/sync", {
          method: "POST",
          ...jsonBody({ session_id: sessionId }),
        });
      } catch {
        // Older bridges, or no sessions:write: the list still refreshes with what the run stored.
      }
      await client.invalidateQueries({ queryKey: artifactKeys.all(instance) });
    },
    [client, instance],
  );
}

/** The control plane URL that serves an artefact: `inline` for the isolated preview, `attachment` to download. */
export function artifactContentUrl(
  instance: string,
  artifact: Pick<Artifact, "session_id" | "storage_key" | "filename">,
  disposition: "inline" | "attachment" = "inline",
): string {
  const key = artifact.storage_key.split("/").map(encodeURIComponent).join("/");
  return apiUrl(
    `/api/v1/instances/${encodeURIComponent(instance)}/artifacts/${encodeURIComponent(artifact.session_id)}/content/${key}${query({ filename: artifact.filename, disposition })}`,
  );
}

/** The URL of a share link's bytes. */
export function sharedContentUrl(token: string, disposition: "inline" | "attachment" = "inline"): string {
  return apiUrl(`/api/v1/shares/${encodeURIComponent(token)}/content${query({ disposition })}`);
}

/** The web app path a share link opens. */
export function shareLink(path: string): string {
  return `${window.location.origin}${path}`;
}

export class ArtifactLoadError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ArtifactLoadError";
    this.status = status;
  }
}

async function problemMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string; title?: string };
    return body.detail ?? body.title ?? `HTTP ${String(response.status)}`;
  } catch {
    return `HTTP ${String(response.status)}`;
  }
}

/** Fetch an artefact's bytes (same origin, session cookie). */
export async function fetchArtifact(url: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch(url, { credentials: "same-origin", ...(signal ? { signal } : {}) });
  if (!response.ok) throw new ArtifactLoadError(response.status, await problemMessage(response));
  return response.blob();
}

/** Start a download of `url` under `filename` without leaving the page. */
export function downloadUrl(url: string, filename: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
}
