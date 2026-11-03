// The draft being edited: one config document in the client, autosaved to the AgentOS draft (2 s idle) with a
// revision check, and projected into generated Python (250 ms after the last edit).
import {
  describeError,
  problemCode,
  studioCodegen,
  studioGetComponentOptions,
  studioNewDraft,
  studioRegistryOptions,
  studioSaveDraft,
  studioSchemaOptions,
  type CodegenOut,
  type ComponentDetailOut,
  type RegistryEntryOut,
  type VersionOut,
} from "@agnostic/api";
import { STALE_TIME, useDebouncedCallback, withQueryFn } from "@agnostic/core";
import { toast } from "@agnostic/ui";
import { keepPreviousData, skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { isRecord, pinsFrom, type Config, type EditableKind } from "./config";

export const AUTOSAVE_MS = 2_000;
export const CODEGEN_MS = 250;

export type SaveState = "saved" | "dirty" | "saving" | "conflict" | "error";

export type Conflict = {
  savedBy: string | undefined;
  savedAt: string | undefined;
  config: Config | undefined;
  revision: string | undefined;
};

/** The value after it stopped changing for `delay` ms. */
export function useDebouncedValue<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSettled(value);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);
  return settled;
}

export function useComponent(instance: string, componentId: string) {
  const options = studioGetComponentOptions({ path: { instance, component_id: componentId } });
  return useQuery({
    ...withQueryFn(options),
    staleTime: STALE_TIME.live,
    enabled: Boolean(instance && componentId),
    retry: false,
  });
}

export function useRegistry(instance: string) {
  const options = studioRegistryOptions({ path: { instance } });
  const query = useQuery({ ...withQueryFn(options), staleTime: STALE_TIME.config });
  const entries = useMemo(() => query.data?.entries ?? [], [query.data]);
  const byType = useCallback((type: string) => entries.filter((entry) => entry.type === type), [entries]);
  const find = useCallback(
    (type: string, name: string): RegistryEntryOut | undefined =>
      entries.find((entry) => entry.type === type && (entry.name === name || entry.id === name)),
    [entries],
  );
  return { ...query, entries, byType, find };
}

export type FieldInfo = {
  section: string;
  label: string;
  help?: string;
  widget: string;
  order: number;
  default?: unknown;
  legacy?: boolean;
  options?: string[];
};
export type Section = { id: string; label: string; fields: string[] };

/** Field metadata and sections from the config's JSON Schema (`GET /studio/schema/{kind}`). */
export function useConfigSchema(kind: EditableKind) {
  const options = studioSchemaOptions({ path: { kind } });
  const query = useQuery({ ...withQueryFn(options), staleTime: Infinity });
  return useMemo(() => {
    const schema = query.data ?? {};
    const properties = isRecord(schema.properties) ? schema.properties : {};
    const fields: Record<string, FieldInfo> = {};
    for (const [name, property] of Object.entries(properties)) {
      if (!isRecord(property) || !isRecord(property["x-agnostic"])) continue;
      const meta = property["x-agnostic"] as Omit<FieldInfo, "options">;
      fields[name] = { ...meta, ...enumOptions(property) };
    }
    const sections = Array.isArray(schema["x-agnostic-sections"])
      ? (schema["x-agnostic-sections"] as Section[])
      : [];
    return { fields, sections, isPending: query.isPending, isError: query.isError };
  }, [query.data, query.isPending, query.isError]);
}

function enumOptions(property: Record<string, unknown>): { options?: string[] } {
  const branches = Array.isArray(property.anyOf) ? property.anyOf : [property];
  for (const branch of branches) {
    if (isRecord(branch) && Array.isArray(branch.enum)) return { options: branch.enum.map(String) };
  }
  return {};
}

export type DraftDocument = {
  detail: ComponentDetailOut | undefined;
  isPending: boolean;
  error: unknown;
  kind: EditableKind;
  draft: VersionOut | undefined;
  /** The version the draft is compared with: the current version, else the one it is based on. */
  base: VersionOut | undefined;
  config: Config | undefined;
  setConfig: (update: (config: Config) => Config) => void;
  pins: Record<string, number>;
  setPin: (componentId: string, version: number | undefined) => void;
  state: SaveState;
  savedAt: Date | undefined;
  save: () => Promise<boolean>;
  conflict: Conflict | undefined;
  resolveConflict: (keep: "mine" | "theirs") => void;
  startDraft: (fromVersion?: number) => Promise<void>;
  startingDraft: boolean;
  code: CodegenOut | undefined;
  codeError: unknown;
};

export function useDraftDocument(instance: string, componentId: string): DraftDocument {
  const queryClient = useQueryClient();
  const detailOptions = studioGetComponentOptions({ path: { instance, component_id: componentId } });
  const detail = useComponent(instance, componentId);
  const kind: EditableKind = detail.data?.component.kind === "team" ? "team" : "agent";
  const draft = detail.data?.draft ?? undefined;
  const base = detail.data?.current ?? undefined;

  const [config, setConfigState] = useState<Config | undefined>(undefined);
  const [pins, setPins] = useState<Record<string, number>>({});
  const [state, setState] = useState<SaveState>("saved");
  const [savedAt, setSavedAt] = useState<Date | undefined>(undefined);
  const [conflict, setConflict] = useState<Conflict | undefined>(undefined);
  const revision = useRef<string | undefined>(undefined);
  const loaded = useRef<number | undefined>(undefined);
  const latest = useRef<{ config: Config | undefined; pins: Record<string, number> }>({ config, pins });
  useEffect(() => {
    latest.current = { config, pins };
  }, [config, pins]);

  useEffect(() => {
    if (!draft || loaded.current === draft.version) return;
    loaded.current = draft.version;
    revision.current = draft.revision;
    setConfigState(draft.config ?? {});
    setPins(pinsFrom(draft.links));
    setState("saved");
    setSavedAt(draft.saved_at ? new Date(draft.saved_at) : undefined);
  }, [draft]);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!draft || !latest.current.config) return undefined;
      return (
        await studioSaveDraft({
          path: { instance, component_id: componentId, version: draft.version },
          body: {
            config: latest.current.config,
            revision: revision.current ?? null,
            pins: latest.current.pins,
          },
          throwOnError: true,
        })
      ).data;
    },
    onMutate: () => {
      setState("saving");
    },
    onSuccess: (saved) => {
      if (!saved) return;
      revision.current = saved.revision;
      setSavedAt(new Date());
      setState((current) => (current === "saving" ? "saved" : current));
      void queryClient.invalidateQueries({ queryKey: detailOptions.queryKey });
    },
    onError: (error) => {
      if (problemCode(error) === "version_conflict") {
        const body = error as unknown as Record<string, unknown>;
        setConflict({
          savedBy: typeof body.saved_by === "string" ? body.saved_by : undefined,
          savedAt: typeof body.saved_at === "string" ? body.saved_at : undefined,
          config: isRecord(body.config) ? body.config : undefined,
          revision: typeof body.revision === "string" ? body.revision : undefined,
        });
        setState("conflict");
        return;
      }
      setState("error");
      toast.error(describeError(error).reason);
    },
  });

  const save = useCallback(async (): Promise<boolean> => {
    if (state === "conflict") return false;
    try {
      await mutation.mutateAsync();
      return true;
    } catch {
      return false;
    }
  }, [mutation, state]);
  const autosave = useDebouncedCallback(() => {
    void save();
  }, AUTOSAVE_MS);

  const setConfig = useCallback(
    (update: (current: Config) => Config) => {
      setConfigState((current) => (current ? update(current) : current));
      setState((current) => (current === "conflict" ? current : "dirty"));
      autosave();
    },
    [autosave],
  );
  const setPin = useCallback(
    (child: string, version: number | undefined) => {
      setPins((current) => {
        const next = { ...current };
        if (version === undefined) {
          // eslint-disable-next-line @typescript-eslint/no-dynamic-delete -- pins are keyed by component id
          delete next[child];
        } else {
          next[child] = version;
        }
        return next;
      });
      setState((current) => (current === "conflict" ? current : "dirty"));
      autosave();
    },
    [autosave],
  );

  const resolveConflict = useCallback(
    (keep: "mine" | "theirs") => {
      const found = conflict;
      setConflict(undefined);
      if (!found) return;
      revision.current = found.revision;
      if (keep === "theirs") {
        if (found.config) setConfigState(found.config);
        setState("saved");
        return;
      }
      setState("dirty");
      void mutation.mutateAsync().catch(() => undefined);
    },
    [conflict, mutation],
  );

  const newDraft = useMutation({
    mutationFn: async (fromVersion: number | undefined) =>
      (
        await studioNewDraft({
          path: { instance, component_id: componentId },
          body: { from_version: fromVersion ?? null },
          throwOnError: true,
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: detailOptions.queryKey });
    },
    onError: (error) => toast.error(describeError(error).reason),
  });

  const settled = useDebouncedValue(config, CODEGEN_MS);
  const code = useQuery({
    queryKey: [instance, "studio", "codegen", kind, settled, base?.config ?? null],
    queryFn: settled
      ? async () =>
          (
            await studioCodegen({
              path: { instance },
              body: { kind, config: settled, base_config: base?.config ?? null },
              throwOnError: true,
            })
          ).data
      : skipToken,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });

  return {
    detail: detail.data,
    isPending: detail.isPending,
    error: detail.error,
    kind,
    draft,
    base,
    config,
    setConfig,
    pins,
    setPin,
    state,
    savedAt,
    save,
    conflict,
    resolveConflict,
    startDraft: async (fromVersion?: number) => {
      await newDraft.mutateAsync(fromVersion).catch(() => undefined);
    },
    startingDraft: newDraft.isPending,
    code: code.data,
    codeError: code.error,
  };
}
