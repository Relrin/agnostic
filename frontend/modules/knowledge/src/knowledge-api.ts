// AgentOS knowledge routes through the gateway (as the signed-in person), plus the control plane's knowledge helpers.
// Query keys are `[instance, "agentos", "knowledge", …]` so an ingest or edit refreshes every knowledge view.
import {
  gatewayJson,
  instanceRequest,
  isProblem,
  jsonBody,
  type AgentOS,
  type InstanceRequest,
  type ContentPageOut,
} from "@agnostic/api";
import { STALE_TIME } from "@agnostic/core";
import { skipToken, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

export type ContentRow = AgentOS.ContentResponseSchema & { kind?: string };
export type KnowledgeSettings = AgentOS.ConfigResponseSchema;

export function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== "") search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Partial keys of the generated control-plane queries (filtered content, knowledge bases). */
export const CONTENT_KEY = [{ _id: "contextKnowledgeContent" }];
export const BASES_KEY = [{ _id: "contextKnowledgeBases" }];

export const knowledgeKeys = {
  all: (instance: string) => [instance, "agentos", "knowledge"] as const,
  settings: (instance: string, kb: string) => [instance, "agentos", "knowledge", "settings", kb] as const,
  status: (instance: string, id: string) => [instance, "agentos", "knowledge", "status", id] as const,
  sources: (instance: string, kb: string) => [instance, "agentos", "knowledge", "sources", kb] as const,
  files: (instance: string, kb: string, source: string, prefix: string) =>
    [instance, "agentos", "knowledge", "files", kb, source, prefix] as const,
};

/** `/knowledge/config`: readers, chunkers, remote sources and vector databases of one knowledge base. */
export function useKnowledgeSettings(instance: string, kb: string | undefined) {
  return useQuery({
    queryKey: knowledgeKeys.settings(instance, kb ?? ""),
    queryFn: kb
      ? () => gatewayJson<KnowledgeSettings>(instance, `knowledge/config${query({ knowledge_id: kb })}`)
      : skipToken,
    staleTime: STALE_TIME.config,
  });
}

/** Polls `/knowledge/content/{id}/status` every 3 s for each processing row; a finished row refreshes the list. */
export function useProcessingStatus(instance: string, kb: string | undefined, rows: readonly ContentRow[]) {
  const client = useQueryClient();
  const processing = rows.filter((row) => row.status === "processing");
  return useQueries({
    queries: processing.map((row) => ({
      queryKey: knowledgeKeys.status(instance, row.id),
      queryFn: async () => {
        const status = await gatewayJson<AgentOS.ContentStatusResponse>(
          instance,
          `knowledge/content/${encodeURIComponent(row.id)}/status${query({ knowledge_id: kb })}`,
        );
        if (status.status !== "processing") void client.invalidateQueries({ queryKey: CONTENT_KEY });
        return status;
      },
      refetchInterval: (state: { state: { data?: AgentOS.ContentStatusResponse | undefined } }) =>
        state.state.data?.status === "processing" || state.state.data === undefined ? 3000 : false,
    })),
    combine: (results) =>
      new Map(
        results.flatMap((result, index) => {
          const row = processing[index];
          return row && result.data ? [[row.id, result.data] as const] : [];
        }),
      ),
  });
}

export type IngestCommon = {
  name: string;
  metadata: Record<string, string>;
  readerId: string | undefined;
  chunker: string | undefined;
};

function commonFields(form: FormData | URLSearchParams, common: IngestCommon): void {
  if (common.name.trim()) form.set("name", common.name.trim());
  if (Object.keys(common.metadata).length > 0) form.set("metadata", JSON.stringify(common.metadata));
  if (common.readerId) form.set("reader_id", common.readerId);
  if (common.chunker) form.set("chunker", common.chunker);
}

/**
 * Multipart upload through the gateway with progress. The browser streams the file from disk and the gateway streams
 * it on to AgentOS, so large files never sit in memory on either side.
 */
export function uploadFile(
  instance: string,
  kb: string,
  file: File,
  common: IngestCommon,
  onProgress: (fraction: number) => void,
): Promise<ContentRow> {
  const form = new FormData();
  form.set("file", file, file.name);
  commonFields(form, { ...common, name: common.name || file.name });
  // XMLHttpRequest, not fetch: only it reports upload progress.
  const target = instanceRequest(instance, `knowledge/content${query({ knowledge_id: kb })}`, "POST");
  return target.then((resolved) => send(resolved, form, onProgress));
}

function send(
  target: InstanceRequest,
  form: FormData,
  onProgress: (fraction: number) => void,
): Promise<ContentRow> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", target.url);
    request.withCredentials = target.credentials !== "omit";
    target.headers.forEach((value, name) => {
      request.setRequestHeader(name, value);
    });
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    request.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(request.responseText);
      } catch {
        body = undefined;
      }
      if (request.status >= 200 && request.status < 300) {
        resolve(body as ContentRow);
        return;
      }
      if (isProblem(body)) {
        // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
        reject(body);
        return;
      }
      const detail =
        typeof body === "object" && body !== null && "detail" in body ? String(body.detail) : undefined;
      reject(new Error(detail ?? `Upload failed: HTTP ${String(request.status)}`));
    };
    request.onerror = () => {
      reject(new Error("The upload was interrupted."));
    };
    request.send(form);
  });
}

export type IngestRequest =
  | { kind: "url"; url: string; common: IngestCommon }
  | { kind: "text"; text: string; common: IngestCommon }
  | { kind: "remote"; sourceId: string; paths: string[]; common: IngestCommon };

export function useIngest(instance: string, kb: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (request: IngestRequest) => {
      const suffix = query({ knowledge_id: kb });
      if (request.kind === "remote") {
        for (const path of request.paths) {
          const form = new URLSearchParams({ config_id: request.sourceId, path });
          commonFields(form, {
            ...request.common,
            name: request.paths.length > 1 ? "" : request.common.name,
          });
          await gatewayJson(instance, `knowledge/remote-content${suffix}`, { method: "POST", body: form });
        }
        return request.paths.length;
      }
      const form = new FormData();
      if (request.kind === "url") form.set("url", request.url);
      else form.set("text_content", request.text);
      commonFields(form, request.common);
      await gatewayJson(instance, `knowledge/content${suffix}`, { method: "POST", body: form });
      return 1;
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: CONTENT_KEY });
      await client.invalidateQueries({ queryKey: BASES_KEY });
    },
  });
}

/** Metadata edit (form-encoded PATCH), re-ingest and delete of one content row. */
export function useContentActions(instance: string, kb: string) {
  const client = useQueryClient();
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: CONTENT_KEY });
    await client.invalidateQueries({ queryKey: BASES_KEY });
    await client.invalidateQueries({ queryKey: knowledgeKeys.all(instance) });
  };
  const suffix = query({ knowledge_id: kb });
  const update = useMutation({
    mutationFn: ({
      id,
      name,
      description,
      metadata,
    }: {
      id: string;
      name: string;
      description: string;
      metadata: Record<string, string>;
    }) =>
      gatewayJson<ContentRow>(instance, `knowledge/content/${encodeURIComponent(id)}${suffix}`, {
        method: "PATCH",
        body: new URLSearchParams({ name, description, metadata: JSON.stringify(metadata) }),
      }),
    onSuccess: refresh,
  });
  const reingest = useMutation({
    mutationFn: ({ id }: { id: string }) =>
      gatewayJson(instance, `knowledge/content/${encodeURIComponent(id)}/refresh${suffix}`, {
        method: "POST",
      }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: ({ id }: { id: string }) =>
      gatewayJson(instance, `knowledge/content/${encodeURIComponent(id)}${suffix}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  return { update, reingest, remove };
}

export type SearchResult = { results: AgentOS.VectorSearchResult[]; latencyMs: number; searchType: string };

export function useRetrieval(instance: string, kb: string) {
  return useMutation({
    mutationFn: async ({
      text,
      filters,
      topK,
      searchType,
    }: {
      text: string;
      filters: Record<string, string>;
      topK: number;
      searchType: string;
    }): Promise<SearchResult> => {
      const started = performance.now();
      const body = await gatewayJson<AgentOS.PaginatedResponseVectorSearchResult>(
        instance,
        "knowledge/search",
        {
          method: "POST",
          ...jsonBody({
            query: text,
            knowledge_id: kb,
            max_results: topK,
            search_type: searchType,
            filters: Object.keys(filters).length > 0 ? filters : undefined,
            meta: { limit: topK, page: 1 },
          }),
        },
      );
      const measured = performance.now() - started;
      return {
        results: body.data,
        latencyMs: body.meta.search_time_ms ?? measured,
        searchType,
      };
    },
  });
}

export function useRemoteSources(instance: string, kb: string | undefined) {
  return useQuery({
    queryKey: knowledgeKeys.sources(instance, kb ?? ""),
    queryFn: kb
      ? async () => {
          const body = await gatewayJson<
            AgentOS.RemoteContentSourceSchema[] | { data?: AgentOS.RemoteContentSourceSchema[] }
          >(instance, `knowledge/${encodeURIComponent(kb)}/sources`);
          return Array.isArray(body) ? body : (body.data ?? []);
        }
      : skipToken,
    staleTime: STALE_TIME.config,
  });
}

export function useRemoteFiles(instance: string, kb: string, source: string | undefined, prefix: string) {
  return useQuery({
    queryKey: knowledgeKeys.files(instance, kb, source ?? "", prefix),
    queryFn: source
      ? () =>
          gatewayJson<AgentOS.SourceFilesResponseSchema>(
            instance,
            `knowledge/${encodeURIComponent(kb)}/sources/${encodeURIComponent(source)}/files${query({
              prefix,
              delimiter: "/",
              page: 1,
              limit: 100,
            })}`,
          )
      : skipToken,
    staleTime: STALE_TIME.list,
  });
}

/** Whether a remote file or upload was ingested already: a content row with its name or key. */
export function alreadyIndexed(
  names: ReadonlySet<string>,
  candidate: { name: string; key?: string },
): boolean {
  return names.has(candidate.name) || (candidate.key !== undefined && names.has(candidate.key));
}

export type ContentPage = ContentPageOut;
