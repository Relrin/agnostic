// The draft being edited: one config document in the client, autosaved to the AgentOS draft (2 s idle) with a
// revision check, and projected into generated Python (250 ms after the last edit).
//
// Once someone edits the code, the draft is code-backed: their code is the artifact. Typing is read back into the
// config 300 ms after the last keystroke (`/studio/parse`); a form edit is written into the code instead of
// regenerating it (`/studio/transform`, keeping comments and layout); saves carry the code, which the server checks
// reads as the config. Code that doesn't parse leaves the config at the last version that did, and isn't saved.
import {
  describeError,
  problemCode,
  studioCodegen,
  studioGetCodeComponentOptions,
  studioGetCodeDocumentOptions,
  studioGetComponentOptions,
  studioNewDraft,
  studioParseCode,
  studioRegistryOptions,
  studioSaveDraft,
  studioSchemaOptions,
  studioTransformCode,
  type CodeComponentOut,
  type CodeDiagnosticOut,
  type CodegenOut,
  type ComponentDetailOut,
  type RegistryEntryOut,
  type RuffOut,
  type SpanOut,
  type VersionOut,
} from "@agnostic/api";
import { STALE_TIME, useDebouncedCallback, withQueryFn } from "@agnostic/core";
import { toast } from "@agnostic/ui";
import { keepPreviousData, skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { isRecord, pinsFrom, type Config, type EditableKind } from "./config";

export const AUTOSAVE_MS = 2_000;
export const CODEGEN_MS = 250;
export const PARSE_MS = 300;

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

/** Where the code pane stands: generated from the form, or a person's code and how it reads back. */
export type CodeState = "generated" | "synced" | "parsing" | "invalid" | "writing";

export type SourceCode = {
  /** The person's code is the artifact; otherwise the pane shows generated code. */
  codeBacked: boolean;
  code: string | undefined;
  state: CodeState;
  diagnostics: readonly CodeDiagnosticOut[];
  spans: Record<string, SpanOut>;
  /** Config paths set in code in a way the form can't edit. */
  codeOwned: readonly string[];
  ruff: RuffOut | undefined;
  /** The draft was saved without its code since (e.g. straight on AgentOS), so they may disagree. */
  stale: boolean;
};

const GENERATED: SourceCode = {
  codeBacked: false,
  code: undefined,
  state: "generated",
  diagnostics: [],
  spans: {},
  codeOwned: [],
  ruff: undefined,
  stale: false,
};

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
  /** The code pane's source: generated, or the person's code once they edit it. */
  source: SourceCode;
  /** A person edited the code: from now on the draft is code-backed. */
  setCode: (code: string) => void;
  /** Go back to code generated from the form (the draft stops keeping its code on the next save). */
  generateFromForm: () => void;
  /** Field paths → spans of the code the pane shows. */
  spans: Record<string, SpanOut>;
  /** Where the component lives: stored in Studio (editable), or defined in the runtime's code (read-only). */
  origin: "studio" | "code";
  /** For a component defined in code: its config and where it is defined, once loaded. */
  definedInCode?: CodeComponentOut | undefined;
};

/** Python generated for a config, with the lines that differ from `base` marked (250 ms after the last edit). */
function useGeneratedCode(
  instance: string,
  kind: EditableKind,
  config: Config | undefined,
  base: Config | null | undefined,
) {
  const settled = useDebouncedValue(config, CODEGEN_MS);
  return useQuery({
    queryKey: [instance, "studio", "codegen", kind, settled, base ?? null],
    queryFn: settled
      ? async () =>
          (
            await studioCodegen({
              path: { instance },
              body: { kind, config: settled, base_config: base ?? null },
              throwOnError: true,
            })
          ).data
      : skipToken,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });
}

const ignore = () => undefined;

/**
 * A component defined in the runtime's code, as a document that can't change: its config fills the form and the
 * generated code, and nothing is ever saved. Duplicating it is how it becomes editable.
 */
export function useCodeDocument(instance: string, kind: EditableKind, componentId: string): DraftDocument {
  const found = useQuery({
    ...withQueryFn(studioGetCodeComponentOptions({ path: { instance, kind, component_id: componentId } })),
    staleTime: STALE_TIME.config,
    enabled: Boolean(instance && componentId),
    retry: false,
  });
  const definition = found.data;
  const config = definition?.config ?? undefined;
  const code = useGeneratedCode(instance, kind, config, undefined);
  const detail = useMemo<ComponentDetailOut | undefined>(
    () =>
      definition
        ? {
            component: definition.component,
            editable: false,
            versions: [],
            draft: null,
            current: null,
            owner_group_id: null,
            labels: [],
          }
        : undefined,
    [definition],
  );
  return {
    detail,
    isPending: found.isPending,
    error: found.error,
    kind,
    draft: undefined,
    base: undefined,
    config,
    setConfig: ignore,
    pins: {},
    setPin: ignore,
    state: "saved",
    savedAt: undefined,
    save: () => Promise.resolve(false),
    conflict: undefined,
    resolveConflict: ignore,
    startDraft: () => Promise.resolve(),
    startingDraft: false,
    code: code.data,
    codeError: code.error,
    source: GENERATED,
    setCode: ignore,
    generateFromForm: ignore,
    spans: code.data?.spans ?? {},
    origin: "code",
    definedInCode: definition,
  };
}

export function useDraftDocument(instance: string, componentId: string): DraftDocument {
  const queryClient = useQueryClient();
  const detailOptions = studioGetComponentOptions({ path: { instance, component_id: componentId } });
  const detail = useComponent(instance, componentId);
  const component = detail.data?.component.kind;
  const kind: EditableKind = component === "team" || component === "workflow" ? component : "agent";
  const draft = detail.data?.draft ?? undefined;
  const base = detail.data?.current ?? undefined;

  const [config, setConfigState] = useState<Config | undefined>(undefined);
  const [pins, setPins] = useState<Record<string, number>>({});
  const [state, setState] = useState<SaveState>("saved");
  const [savedAt, setSavedAt] = useState<Date | undefined>(undefined);
  const [conflict, setConflict] = useState<Conflict | undefined>(undefined);
  const revision = useRef<string | undefined>(undefined);
  const loaded = useRef<number | undefined>(undefined);
  const [source, setSource] = useState<SourceCode>(GENERATED);
  const dropCode = useRef(false);
  /** The config the person's code reads as: what the form falls back to when an edit can't reach the code. */
  const codeConfig = useRef<Config | undefined>(undefined);
  const latest = useRef<{ config: Config | undefined; pins: Record<string, number>; source: SourceCode }>({
    config,
    pins,
    source,
  });
  useEffect(() => {
    latest.current = { config, pins, source };
  }, [config, pins, source]);

  useEffect(() => {
    if (!draft || loaded.current === draft.version) return;
    loaded.current = draft.version;
    revision.current = draft.revision;
    setConfigState(draft.config ?? {});
    setPins(pinsFrom(draft.links));
    setState("saved");
    setSavedAt(draft.saved_at ? new Date(draft.saved_at) : undefined);
  }, [draft]);

  const codeDocument = useQuery({
    ...withQueryFn(
      studioGetCodeDocumentOptions({
        path: { instance, component_id: componentId, version: draft?.version ?? 0 },
      }),
    ),
    enabled: Boolean(draft),
    staleTime: Infinity,
    retry: false,
  });
  const loadedCode = useRef<number | undefined>(undefined);

  const mutation = useMutation({
    mutationFn: async () => {
      const current = latest.current;
      if (!draft || !current.config) return undefined;
      const human = current.source;
      // The server refuses code that doesn't read as the config: wait until it parses again.
      if (human.codeBacked && human.state !== "synced") return undefined;
      const code = human.codeBacked ? (human.code ?? null) : dropCode.current ? "" : null;
      const saved = (
        await studioSaveDraft({
          path: { instance, component_id: componentId, version: draft.version },
          body: { config: current.config, revision: revision.current ?? null, pins: current.pins, code },
          throwOnError: true,
        })
      ).data;
      if (code === "") dropCode.current = false;
      return saved;
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

  const parse = useDebouncedCallback((code: string) => {
    void studioParseCode({
      path: { instance },
      body: { kind, code, component_id: componentId },
      throwOnError: true,
    })
      .then(({ data }) => {
        if (latest.current.source.code !== code) return;
        setSource((current) => ({
          ...current,
          state: data.ok && data.config ? "synced" : "invalid",
          diagnostics: data.diagnostics,
          spans: data.spans,
          codeOwned: data.code_owned,
          ruff: data.ruff,
        }));
        if (data.ok && data.config) {
          codeConfig.current = data.config;
          setConfigState(data.config);
          autosave();
        }
      })
      .catch((error: unknown) => {
        setSource((current) => ({ ...current, state: "invalid" }));
        toast.error(describeError(error).reason);
      });
  }, PARSE_MS);

  const write = useDebouncedCallback((next: Config) => {
    const code = latest.current.source.code;
    if (code === undefined) return;
    void studioTransformCode({
      path: { instance },
      body: { kind, code, config: next, component_id: componentId },
      throwOnError: true,
    })
      .then(({ data }) => {
        if (data.equivalent) {
          codeConfig.current = data.config ?? next;
          setSource((current) => ({
            ...current,
            code: data.code,
            state: "synced",
            diagnostics: data.diagnostics,
            spans: data.spans,
            codeOwned: data.code_owned,
            ruff: data.ruff,
          }));
          autosave();
          return;
        }
        const reason = data.diagnostics.find((item) => item.severity === "error")?.message;
        toast.error(reason ?? "This change can't be written into the code; edit it in the code instead.");
        if (codeConfig.current) setConfigState(codeConfig.current);
        setSource((current) => ({ ...current, state: "synced" }));
      })
      .catch((error: unknown) => {
        toast.error(describeError(error).reason);
        if (codeConfig.current) setConfigState(codeConfig.current);
        setSource((current) => ({ ...current, state: "synced" }));
      });
  }, PARSE_MS);

  const setConfig = useCallback(
    (update: (current: Config) => Config) => {
      const current = latest.current.config;
      if (!current) return;
      const next = update(current);
      // Kept ahead of the render, so edits in quick succession build on each other.
      latest.current = { ...latest.current, config: next };
      setConfigState(next);
      setState((saved) => (saved === "conflict" ? saved : "dirty"));
      if (latest.current.source.codeBacked) {
        setSource((existing) => ({ ...existing, state: "writing" }));
        write(next);
      } else {
        autosave();
      }
    },
    [autosave, write],
  );

  const setCode = useCallback(
    (code: string) => {
      setSource((current) => ({ ...current, codeBacked: true, code, state: "parsing", stale: false }));
      setState((current) => (current === "conflict" ? current : "dirty"));
      parse(code);
    },
    [parse],
  );

  const generateFromForm = useCallback(() => {
    dropCode.current = true;
    codeConfig.current = undefined;
    setSource(GENERATED);
    setState((current) => (current === "conflict" ? current : "dirty"));
    autosave();
  }, [autosave]);

  useEffect(() => {
    const found = codeDocument.data;
    if (!draft || !found || loadedCode.current === draft.version) return;
    loadedCode.current = draft.version;
    // Someone already started editing the code: their text wins over what the draft kept.
    if (latest.current.source.codeBacked) return;
    const kept = found.code_backed ? found.code : null;
    setSource(
      kept === null
        ? GENERATED
        : { ...GENERATED, codeBacked: true, code: kept, state: "parsing", stale: found.stale },
    );
    if (kept !== null) parse(kept);
  }, [codeDocument.data, draft, parse]);
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
        loadedCode.current = undefined;
        void codeDocument.refetch();
        return;
      }
      setState("dirty");
      void mutation.mutateAsync().catch(() => undefined);
    },
    [conflict, mutation, codeDocument],
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

  const code = useGeneratedCode(instance, kind, config, base?.config);

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
    source,
    setCode,
    generateFromForm,
    spans: source.codeBacked ? source.spans : (code.data?.spans ?? {}),
    origin: "studio",
  };
}
