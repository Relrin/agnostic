// AgentOS file-system routes through the gateway (read-only in AgentOS 3.1). Query keys are
// `[instance, "agentos", "files", …]`.
import { gatewayJson, type AgentOS } from "@agnostic/api";
import { STALE_TIME } from "@agnostic/core";
import { skipToken, useQuery } from "@tanstack/react-query";

export type Entry = AgentOS.FileSystemEntry;
export type Namespace = AgentOS.FileSystemNamespace;
/** The `/config` section this page reads (the generated type is an open object). */
export type OsConfig = { filesystem?: AgentOS.FileSystemConfig | null };

export function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== "") search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function useNamespaces(instance: string) {
  return useQuery({
    queryKey: [instance, "agentos", "config"],
    queryFn: instance ? () => gatewayJson<OsConfig>(instance, "config") : skipToken,
    staleTime: STALE_TIME.config,
    select: (config) => config.filesystem?.namespaces ?? [],
  });
}

export function useEntries(
  instance: string,
  namespace: string | undefined,
  directory: string,
  enabled = true,
) {
  return useQuery({
    queryKey: [instance, "agentos", "files", "entries", namespace, directory],
    queryFn:
      namespace && enabled
        ? () =>
            gatewayJson<AgentOS.FileSystemListResponse>(
              instance,
              `filesystem/entries${query({ namespace, directory, page: 1, limit: 100 })}`,
            )
        : skipToken,
    staleTime: STALE_TIME.list,
  });
}

export function useContent(instance: string, namespace: string | undefined, entry: Entry | undefined) {
  return useQuery({
    queryKey: [instance, "agentos", "files", "content", namespace, entry?.path, entry?.user_id],
    queryFn:
      namespace && entry
        ? () =>
            gatewayJson<AgentOS.FileSystemContentResponse>(
              instance,
              `filesystem/content${query({ namespace, path: entry.path, user_id: entry.user_id ?? undefined })}`,
            )
        : skipToken,
    staleTime: STALE_TIME.list,
  });
}

export function useSearchFiles(
  instance: string,
  namespace: string | undefined,
  directory: string,
  text: string,
) {
  return useQuery({
    queryKey: [instance, "agentos", "files", "search", namespace, directory, text],
    queryFn:
      namespace && text
        ? () =>
            gatewayJson<AgentOS.FileSystemSearchResponse>(
              instance,
              `filesystem/search${query({ namespace, directory, query: text, page: 1, limit: 100 })}`,
            )
        : skipToken,
    staleTime: STALE_TIME.list,
  });
}

/** "reports/daily-brief/2026-10-30.md" → "2026-10-30.md". */
export function baseName(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

export function extension(path: string): string {
  const name = baseName(path);
  return name.includes(".") ? (name.split(".").at(-1) ?? "").toLowerCase() : "";
}

/** A small CSV parser for previews: quoted fields, escaped quotes, commas and newlines inside quotes. */
export function parseCsv(text: string, maxRows = 200): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length && rows.length < maxRows; index += 1) {
    const char = text.charAt(index);
    if (quoted) {
      if (char === '"' && text.charAt(index + 1) === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text.charAt(index + 1) === "\n") index += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += char;
  }
  if ((field || row.length > 0) && rows.length < maxRows) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

/** "Folder access" sentence: who writes and who only reads this namespace. */
export function accessSentence(namespace: Namespace | undefined): { writers: string[]; readers: string[] } {
  const agents = namespace?.agents ?? [];
  return {
    writers: agents.filter((agent) => (agent.access ?? "full") === "full").map((agent) => agent.id),
    readers: agents.filter((agent) => agent.access === "read_only").map((agent) => agent.id),
  };
}
