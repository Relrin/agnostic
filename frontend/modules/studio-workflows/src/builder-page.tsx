// The workflow builder (`studio/workflows/:id`, `?view=canvas|code&node=`): header (draft chip, Versions, Playground,
// Share, Save draft, Publish), toolbar (Canvas / Code, undo and redo, auto-layout, the validation sentence), then the
// component palette, the canvas (or the code) and the inspector or the Playground, with the problems below. The
// canvas and the code are one document: the selected step highlights its lines, and the cursor in the code selects
// a step. Share exports the workflow as a Langflow flow and imports one.
import {
  describeError,
  studioGetCanvasLayoutOptions,
  studioPutCanvasLayout,
  studioStepStatsOptions,
  studioValidateWorkflow,
} from "@agnostic/api";
import { findInstance, useCan, useDebouncedCallback, useInstances, withQueryFn } from "@agnostic/core";
import {
  CodePane,
  ConflictDialog,
  DraftChip,
  FAMILY_LABEL,
  IncomingChip,
  PublishDialog,
  SourceBar,
  VersionsDrawer,
  incomingMarks,
  unpublished,
  useComponentSource,
  useConfigSchema,
  useDebouncedValue,
  useDraftDocument,
  useRegistry,
  type DraftDocument,
  type FormContext,
} from "@agnostic/studio";
import {
  Breadcrumb,
  Button,
  Callout,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  ErrorState,
  LoadingRows,
  SegmentedControl,
  cn,
  toast,
} from "@agnostic/ui";
import { skipToken, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import {
  CircleAlert,
  CircleCheck,
  Code2,
  Download,
  History,
  LayoutGrid,
  Play,
  Redo2,
  Share2,
  Undo2,
  Upload,
  Waypoints,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { CanvasProvider, WorkflowCanvas, useCanvas } from "./canvas";
import { BuilderProvider, useActions, type Builder } from "./context";
import { useExecutorDetails } from "./executor-details";
import { createBuilderStore, useBuilder } from "./history";
import { Inspector } from "./inspector";
import { fromLangflow, toLangflow, type ImportResult } from "./langflow";
import { followOffsets, readCanvasState, type CanvasState } from "./notes";
import { Palette } from "./palette";
import { ProblemsPanel, nodePathOf, problemCounts } from "./problems";
import { PlaygroundPanel, stepResults, useTestRun } from "./run-test";
import { useExecutors, useWorkflowSchema } from "./schema";
import { followPaths, stepCount } from "./tree";

type View = "canvas" | "code";
const VALIDATE_MS = 400;
const LAYOUT_SAVE_MS = 1_500;

function useBuilderSearch(): [
  { view: View; node: string | undefined },
  (next: { view?: View; node?: string | undefined }) => void,
] {
  const raw = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const view: View = raw.view === "code" ? "code" : "canvas";
  const node = typeof raw.node === "string" && raw.node ? raw.node : undefined;
  return [
    { view, node },
    (next) => {
      void navigate({
        to: ".",
        search: (previous: Record<string, unknown>) => ({
          ...previous,
          ...("view" in next ? { view: next.view } : {}),
          ...("node" in next ? { node: next.node } : {}),
        }),
        replace: true,
      });
    },
  ];
}

/** `/i/:instance/studio/workflows/:componentId`. */
export function WorkflowBuilderPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  return (
    <CanvasProvider>
      <WorkflowBuilder instance={params.instance ?? ""} componentId={params.componentId ?? ""} />
    </CanvasProvider>
  );
}

function useValidation(instance: string, doc: DraftDocument) {
  const settled = useDebouncedValue(doc.config, VALIDATE_MS);
  return useQuery({
    queryKey: [instance, "studio", "workflow-validate", settled],
    queryFn: settled
      ? async () =>
          (
            await studioValidateWorkflow({
              path: { instance },
              body: { config: settled },
              throwOnError: true,
            })
          ).data
      : skipToken,
    staleTime: Infinity,
    retry: false,
    placeholderData: (previous) => previous,
  });
}

/** Downloads `content` as a file. */
function download(filename: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function ImportDialog({
  result,
  onCancel,
  onApply,
}: {
  result: ImportResult | undefined;
  onCancel: () => void;
  onApply: (result: ImportResult) => void;
}) {
  const notes = result?.notes.length ?? 0;
  const steps = result?.steps.length ?? 0;
  return (
    <Dialog
      open={result !== undefined}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Import the Langflow flow</DialogTitle>
          <DialogDescription>
            {result?.source === "agnostic"
              ? "This flow was exported from Studio: it replaces the draft's steps exactly as they were."
              : "Its components that pass messages on become steps, in the order they run. It replaces the draft's steps; Undo brings them back."}
          </DialogDescription>
        </DialogHeader>
        {result && (
          <div className="flex flex-col gap-2 text-[13px]">
            <p className="m-0">
              {`${String(steps)} top-level step${steps === 1 ? "" : "s"}${notes ? `, ${String(notes)} note${notes === 1 ? "" : "s"}` : ""}.`}
            </p>
            {result.warnings.length > 0 && (
              <ul aria-label="What doesn't carry over" className="m-0 flex flex-col gap-1 pl-4 text-warning">
                {result.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="secondary" size="32" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="32"
            onClick={() => {
              if (result) onApply(result);
            }}
          >
            Replace the steps
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function WorkflowBuilder({ instance, componentId }: { instance: string; componentId: string }) {
  const doc = useDraftDocument(instance, componentId);
  const source = useComponentSource(instance, componentId);
  const [store] = useState(createBuilderStore);
  const canWrite = useCan("components:write", instance);
  const readOnly = canWrite.allowed !== true || !doc.draft;
  const actions = useActions(doc, store, readOnly);
  const schema = useWorkflowSchema();
  const workflowSchema = useConfigSchema("workflow");
  const registry = useRegistry(instance);
  const { options: executors } = useExecutors(instance, componentId);
  const instances = useInstances();
  const instanceName = findInstance(instances.data, instance)?.display_name ?? instance;
  const [search, setSearch] = useBuilderSearch();
  const [dialog, setDialog] = useState<"versions" | "publish" | undefined>(undefined);
  const [panel, setPanel] = useState<"inspector" | "playground">("inspector");
  const [importing, setImporting] = useState<ImportResult | undefined>(undefined);
  const importInput = useRef<HTMLInputElement>(null);
  const flow = useCanvas();
  const [layoutVersion, setLayoutVersion] = useState(0);
  // A field focused in the form or the code wins over the selected step until the selection changes.
  const [fieldFocus, setFieldFocus] = useState<{ selected: string | undefined; path: string | undefined }>({
    selected: undefined,
    path: undefined,
  });
  const inspector = useRef<HTMLElement>(null);
  const selected = useBuilder(store, (state) => state.selected);
  const canUndo = useBuilder(store, (state) => state.past.length > 0);
  const canRedo = useBuilder(store, (state) => state.future.length > 0);
  const validation = useValidation(instance, doc);
  const run = useTestRun(instance, componentId);
  const details = useExecutorDetails(instance, doc.config);
  const scoped = `/i/${encodeURIComponent(instance)}`;
  const draft = doc.draft;

  // Selection and the URL's `node` follow each other; the selected step is what the code highlights.
  const initial = useRef(search.node);
  useEffect(() => {
    if (initial.current) store.getState().select(initial.current);
  }, [store]);
  useEffect(() => {
    if (selected !== search.node) setSearch({ node: selected });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a new selection writes the URL
  }, [selected]);
  // Selecting a step shows its settings (adjusted while rendering, as React suggests for derived state).
  const [shownSelection, setShownSelection] = useState(selected);
  if (selected !== shownSelection) {
    setShownSelection(selected);
    if (selected) setPanel("inspector");
  }
  const focusedPath = fieldFocus.selected === selected ? (fieldFocus.path ?? selected) : selected;
  const setFocusedPath = (path: string | undefined) => {
    setFieldFocus({ selected: store.getState().selected, path });
  };

  const stats = useQuery({
    ...withQueryFn(
      studioStepStatsOptions({ path: { instance, component_id: componentId }, query: { window: "7d" } }),
    ),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const averages = useMemo(
    () => new Map((stats.data?.steps ?? []).map((item) => [item.name, item.avg_ms])),
    [stats.data],
  );
  const layoutQuery = useQuery({
    ...withQueryFn(
      studioGetCanvasLayoutOptions({
        path: { instance, component_id: componentId },
        query: { version: draft?.version ?? 1 },
      }),
    ),
    enabled: Boolean(draft),
    staleTime: Infinity,
  });
  // Manual moves and sticky notes, as edited here or as last saved for this draft.
  const [canvasState, setCanvasState] = useState<CanvasState | undefined>(undefined);
  const shown = useMemo<CanvasState>(
    () => canvasState ?? readCanvasState(layoutQuery.data?.layout),
    [canvasState, layoutQuery.data],
  );
  const saveLayout = useDebouncedCallback((next: CanvasState) => {
    if (!draft || readOnly) return;
    void studioPutCanvasLayout({
      path: { instance, component_id: componentId },
      body: { version: draft.version, layout: { positions: next.positions, notes: next.notes } },
    });
  }, LAYOUT_SAVE_MS);
  const updateCanvas = (next: Partial<CanvasState>) => {
    const merged = { ...shown, ...next };
    setCanvasState(merged);
    saveLayout(merged);
  };
  // Manual moves are kept by node path: after an edit each one follows its node (removing a step renumbers the
  // steps after it), so a step never takes over the place another one was moved to.
  const previousConfig = useRef(doc.config);
  useEffect(() => {
    const before = previousConfig.current;
    previousConfig.current = doc.config;
    if (!before || !doc.config || before === doc.config) return;
    const positions = followOffsets(shown.positions, followPaths(before, doc.config));
    if (positions !== shown.positions) updateCanvas({ positions });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a new config moves the offsets
  }, [doc.config]);
  const results = useMemo(() => stepResults(run.state?.steps), [run.state?.steps]);
  const problems = useMemo(() => problemCounts(validation.data), [validation.data]);

  if (doc.isPending) return <LoadingRows rows={8} label="Loading the workflow" />;
  if (doc.error || !doc.detail) {
    return (
      <div className="p-6">
        <ErrorState {...describeError(doc.error ?? new Error("This workflow couldn't be found."))} />
      </div>
    );
  }
  const detail = doc.detail;
  const component = detail.component;
  const builder: Builder = { instance, componentId, doc, store, readOnly, actions };
  const count = stepCount(doc.config);
  const sentence = validation.data?.sentence ?? `${String(count)} step${count === 1 ? "" : "s"} · checking…`;
  const valid = validation.data?.validation.ok;
  const inputSchema = doc.config?.input_schema;
  const inputLabel =
    typeof inputSchema === "string" ? inputSchema : inputSchema ? "structured input" : "input";

  const exportFlow = async () => {
    const exported = await toLangflow({
      config: doc.config,
      id: component.id,
      name: component.name,
      inputLabel,
      offsets: shown.positions,
      notes: shown.notes,
      viewport: flow.getViewport(),
    });
    download(`${component.id}.langflow.json`, `${JSON.stringify(exported, null, 2)}\n`);
    toast.success(`Exported ${component.id}.langflow.json`);
  };
  const readImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      setImporting(fromLangflow(JSON.parse(await file.text())));
    } catch (error) {
      toast.error(error instanceof SyntaxError ? "This file isn't JSON." : (error as Error).message);
    }
  };
  const applyImport = (result: ImportResult) => {
    actions.updateWorkflow("Import a Langflow flow", (config) => {
      config.steps = result.steps;
    });
    updateCanvas({ positions: {}, notes: result.notes });
    setImporting(undefined);
    setLayoutVersion((current) => current + 1);
    toast.success("Imported the Langflow flow.");
  };

  const workflowCtx: FormContext | undefined = doc.config
    ? {
        config: doc.config,
        onChange: (update) => {
          actions.updateWorkflow("Edit the workflow settings", (config) => {
            const next = update({ ...config });
            for (const key of Object.keys(config)) if (!(key in next)) Reflect.deleteProperty(config, key);
            Object.assign(config, next);
          });
        },
        spans: doc.spans,
        focusedPath,
        onFocusPath: setFocusedPath,
        registry,
        readOnly,
        isCodeOwned: (path) =>
          doc.source.codeOwned.some((owned) => path === owned || path.startsWith(`${owned}.`)),
        onEditInCode: (path) => {
          setFocusedPath(path);
          setSearch({ view: "code" });
        },
      }
    : undefined;

  return (
    <BuilderProvider value={builder}>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex flex-wrap items-center gap-3 border-b border-border-subtle px-6 py-2.5">
          <Breadcrumb
            items={[
              { label: "Studio" },
              { label: FAMILY_LABEL.workflow, href: `${scoped}/studio/workflows` },
              { label: component.id, mono: true },
            ]}
            renderLink={(crumb) => <Link to={crumb.href}>{crumb.label}</Link>}
          />
          <DraftChip doc={doc} />
          <IncomingChip instance={instance} componentId={componentId} />
          <span className="flex-1" />
          <Button
            variant="outline"
            size="32"
            onClick={() => {
              setDialog("versions");
            }}
          >
            <History aria-hidden />
            Versions
          </Button>
          {draft && canWrite.allowed && (
            <Button
              variant="outline"
              size="32"
              aria-pressed={panel === "playground"}
              className={cn(panel === "playground" && "border-border-dashed bg-surface-hover")}
              onClick={() => {
                setPanel((current) => (current === "playground" ? "inspector" : "playground"));
              }}
            >
              <Play aria-hidden className="fill-accent text-accent" />
              Playground
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="32">
                <Waypoints aria-hidden />
                Share
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => void exportFlow()}>
                <Download aria-hidden />
                Export as Langflow JSON
              </DropdownMenuItem>
              {!readOnly && (
                <DropdownMenuItem
                  onSelect={() => {
                    importInput.current?.click();
                  }}
                >
                  <Upload aria-hidden />
                  Import Langflow JSON…
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
          <input
            ref={importInput}
            type="file"
            accept="application/json,.json"
            aria-label="Langflow flow to import"
            className="hidden"
            onChange={(event) => void readImport(event)}
          />
          {draft && canWrite.allowed && (
            <Button
              variant="secondary"
              size="32"
              disabled={doc.state === "saving" || doc.state === "saved"}
              onClick={() => void doc.save()}
            >
              Save draft
            </Button>
          )}
          {draft && canWrite.allowed && (
            <Button
              variant="primary"
              size="32"
              onClick={() => {
                setDialog("publish");
              }}
            >
              {`Publish v${String(draft.version)}`}
            </Button>
          )}
        </div>
        {!draft && (
          <Callout tone="info" className="mx-6 mt-3" title="No open draft">
            {`The current version is v${String(component.current_version ?? "")}. Start a draft from Versions to edit it.`}
          </Callout>
        )}
        <div className="flex flex-wrap items-center gap-3 border-b border-border-subtle px-6 py-2">
          <SegmentedControl
            label="Builder view"
            value={search.view}
            onValueChange={(view) => {
              setSearch({ view });
            }}
            options={[
              { value: "canvas", label: "Canvas", icon: <Share2 aria-hidden /> },
              { value: "code", label: "Code", icon: <Code2 aria-hidden /> },
            ]}
          />
          <div className="flex items-center gap-1 rounded-[9px] border border-border px-1">
            <Button
              variant="icon"
              size="28"
              aria-label="Undo"
              disabled={!canUndo || readOnly}
              onClick={actions.undo}
            >
              <Undo2 aria-hidden />
            </Button>
            <Button
              variant="icon"
              size="28"
              aria-label="Redo"
              disabled={!canRedo || readOnly}
              onClick={actions.redo}
            >
              <Redo2 aria-hidden />
            </Button>
          </div>
          {search.view === "canvas" && (
            <Button
              variant="ghost"
              size="28"
              onClick={() => {
                updateCanvas({ positions: {} });
                setLayoutVersion((current) => current + 1);
              }}
            >
              <LayoutGrid aria-hidden />
              Auto-layout
            </Button>
          )}
          <span className="flex-1" />
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-[12.5px]",
              valid === false ? "text-danger" : "text-fg-secondary",
            )}
            title="Every Step and every container (Steps, Parallel, Condition, Loop, Router) counts as a step."
            aria-live="polite"
          >
            {valid === false ? (
              <CircleAlert aria-hidden className="size-3.5" />
            ) : (
              <CircleCheck aria-hidden className="size-3.5 text-accent" />
            )}
            {sentence}
            {run.state?.status === "completed" && " · last test passed"}
          </span>
          {unpublished(doc.base?.config, doc.config) && (
            <span className="font-mono text-[11.5px] text-warning">
              {unpublished(doc.base?.config, doc.config)}
            </span>
          )}
        </div>
        <div className="flex min-h-0 flex-1">
          {search.view === "canvas" ? (
            <>
              <Palette executors={executors} registryHref={`${scoped}/studio/registry`} />
              <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-canvas">
                <WorkflowCanvas
                  config={doc.config}
                  inputLabel={inputLabel}
                  results={results}
                  problems={problems}
                  stats={averages}
                  details={details}
                  offsets={shown.positions}
                  notes={shown.notes}
                  onNotes={(notes) => {
                    updateCanvas({ notes });
                  }}
                  onArrange={updateCanvas}
                  onOpenInspector={() => {
                    setPanel("inspector");
                    requestAnimationFrame(() => inspector.current?.focus());
                  }}
                  layoutVersion={layoutVersion}
                />
              </div>
            </>
          ) : (
            <div className="flex min-h-0 min-w-0 flex-1 flex-col p-3">
              <CodePane
                code={doc.code}
                source={doc.source}
                onCode={doc.setCode}
                onGenerate={doc.generateFromForm}
                config={doc.config}
                kind="workflow"
                focusedPath={focusedPath}
                onFocusPath={(path) => {
                  setFocusedPath(path);
                  const node = path ? nodePathOf(path) : undefined;
                  if (node && node !== store.getState().selected) store.getState().select(node);
                }}
                registryHref={(entry) => `${scoped}/studio/registry/tool/${encodeURIComponent(entry)}`}
                uncommitted={undefined}
                pending={doc.state === "dirty"}
                readOnly={readOnly}
                sourceBar={<SourceBar instance={instance} componentId={componentId} canWrite={!readOnly} />}
                incomingMarks={incomingMarks(source.data, doc.draft?.version)}
              />
            </div>
          )}
          {panel === "playground" && draft ? (
            <PlaygroundPanel
              run={run}
              instanceName={instanceName}
              componentName={component.name}
              version={draft.version}
              beforeRun={doc.save}
              onClose={() => {
                setPanel("inspector");
              }}
            />
          ) : (
            <Inspector
              ref={inspector}
              instance={instance}
              componentId={componentId}
              schema={schema}
              executors={executors}
              workflowForm={{
                sections: workflowSchema.sections,
                fields: workflowSchema.fields,
                ctx: workflowCtx,
              }}
              focusedPath={focusedPath}
              onFocusPath={setFocusedPath}
              results={results}
              onOpenCode={() => {
                setSearch({ view: "code" });
              }}
            />
          )}
        </div>
        <ProblemsPanel validation={validation.data} />
        <ImportDialog
          result={importing}
          onCancel={() => {
            setImporting(undefined);
          }}
          onApply={applyImport}
        />
        <VersionsDrawer
          open={dialog === "versions"}
          onOpenChange={(open) => {
            setDialog(open ? "versions" : undefined);
          }}
          instance={instance}
          instanceName={instanceName}
          detail={detail}
        />
        {draft && (
          <PublishDialog
            open={dialog === "publish"}
            onOpenChange={(open) => {
              setDialog(open ? "publish" : undefined);
            }}
            instance={instance}
            componentId={component.id}
            version={draft.version}
            evalsHref={`${scoped}/evals`}
            beforeCheck={doc.save}
            onPublished={() => undefined}
          />
        )}
        <ConflictDialog
          open={doc.conflict !== undefined}
          savedBy={doc.conflict?.savedBy}
          savedAt={doc.conflict?.savedAt}
          onKeep={doc.resolveConflict}
        />
      </div>
    </BuilderProvider>
  );
}
