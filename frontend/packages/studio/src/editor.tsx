// The editor frame shared by agents and teams: header (draft chip, Versions, Run evals, Save draft, Publish vN,
// Promote), the Form / Split / Code layout with the diff summary, and the form, code and test panes.
import {
  describeError,
  studioDiffVersionsOptions,
  type ComponentDetailOut,
  type RegistryEntryOut,
} from "@agnostic/api";
import { findInstance, formatRelative, useCan, useInstances, withQueryFn } from "@agnostic/core";
import { preloadCodeEditor, preloadCodeView } from "@agnostic/editor";
import {
  Breadcrumb,
  Button,
  Callout,
  EmptyState,
  ErrorState,
  LoadingRows,
  SegmentedControl,
  cn,
} from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowLeftRight, CheckCircle2, Code2, Columns2, History, Rows3, Upload } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { CodePane } from "./code-pane";
import { ExplainConfig } from "./explain-config";
import { changedFields, type Config, type EditableKind } from "./config";
import { ConflictDialog, DiffDialog, PromoteDialog, PublishDialog, VersionsDrawer } from "./dialogs";
import { useDraftDocument, useRegistry, type DraftDocument } from "./document";
import { IncomingChip, SourceBar, incomingMarks, useComponentSource } from "./source-bar";
import { fieldId, type FormContext } from "./form";
import { TestPane } from "./test-pane";

export type Layout = "form" | "split" | "code";
const LAYOUTS: readonly Layout[] = ["form", "split", "code"];
export const FAMILY_LABEL: Record<EditableKind, string> = {
  agent: "Agents",
  team: "Agent teams",
  workflow: "Workflows",
};

function useLayout(): [Layout, (layout: Layout) => void] {
  const raw = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const layout = LAYOUTS.includes(raw.layout as Layout) ? (raw.layout as Layout) : "split";
  return [
    layout,
    (next) => {
      void navigate({
        to: ".",
        search: (previous: Record<string, unknown>) => ({ ...previous, layout: next }),
        replace: true,
      });
    },
  ];
}

export function DraftChip({ doc }: { doc: DraftDocument }) {
  const draft = doc.draft;
  if (!draft) return null;
  const basedOn = draft.based_on_version ?? doc.detail?.component.current_version;
  const state =
    doc.state === "saving"
      ? "saving…"
      : doc.state === "dirty"
        ? "unsaved changes"
        : doc.state === "conflict"
          ? "save conflict"
          : doc.state === "error"
            ? "not saved"
            : doc.savedAt
              ? `autosaved ${formatRelative(doc.savedAt)}`
              : "saved";
  return (
    <span
      className="inline-flex h-7 items-center gap-2 rounded-full border border-border-strong px-3 text-[12px] text-fg-secondary"
      aria-live="polite"
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full",
          doc.state === "error" || doc.state === "conflict" ? "bg-danger" : "bg-warning",
        )}
      />
      {`Draft v${String(draft.version)}${basedOn && basedOn !== draft.version ? ` · based on v${String(basedOn)}` : ""} · ${state}`}
    </span>
  );
}

/** "↑ 1 unpublished · mode changed": what the draft changes compared with the current version. */
export function unpublished(base: Config | null | undefined, config: Config | undefined): string | undefined {
  if (!base || !config) return undefined;
  const fields = changedFields(base, config);
  if (!fields.length) return undefined;
  return fields.length === 1
    ? `↑ 1 unpublished · ${fields[0] ?? ""} changed`
    : `↑ ${String(fields.length)} unpublished`;
}

export function StudioEditor({
  instance,
  componentId,
  kind,
  renderForm,
  toolbarExtra,
}: {
  instance: string;
  componentId: string;
  kind: EditableKind;
  /** The form for this kind; it gets the shared form context (config, registry, spans, focus). */
  renderForm: (ctx: FormContext, doc: DraftDocument) => ReactNode;
  toolbarExtra?: (doc: DraftDocument) => ReactNode;
}) {
  const doc = useDraftDocument(instance, componentId);
  const registry = useRegistry(instance);
  const instances = useInstances();
  const found = findInstance(instances.data, instance);
  const instanceName = found?.display_name ?? instance;
  const canWrite = useCan("components:write", instance);
  const canPromote = useCan("studio:promote", instance);
  const [layout, setLayout] = useLayout();
  const [focusedPath, setFocusedPath] = useState<string | undefined>(undefined);
  const [dialog, setDialog] = useState<"diff" | "versions" | "publish" | "promote" | undefined>(undefined);
  const scoped = `/i/${encodeURIComponent(instance)}`;

  const detail: ComponentDetailOut | undefined = doc.detail;
  const draft = doc.draft;
  const base = doc.base;
  const diffOptions = studioDiffVersionsOptions({
    path: { instance, component_id: componentId },
    query: { from: base?.version ?? 0, to: draft?.version ?? 0 },
  });
  const diff = useQuery({ ...withQueryFn(diffOptions), enabled: Boolean(base && draft) });
  const source = useComponentSource(instance, componentId);

  useEffect(() => {
    if (!focusedPath) return;
    const element = document.getElementById(fieldId(focusedPath));
    if (element && typeof element.scrollIntoView === "function") element.scrollIntoView({ block: "nearest" });
  }, [focusedPath]);

  if (doc.isPending) return <LoadingRows rows={8} label="Loading the editor" />;
  if (doc.error || !detail) {
    return (
      <div className="p-6">
        <ErrorState {...describeError(doc.error ?? new Error("This component couldn't be found."))} />
      </div>
    );
  }

  const schemaName = typeof doc.config?.output_schema === "string" ? doc.config.output_schema : undefined;
  const outputSchema: RegistryEntryOut | undefined = schemaName
    ? registry.find("schema", schemaName)
    : undefined;
  const ctx: FormContext | undefined = doc.config
    ? {
        config: doc.config,
        onChange: doc.setConfig,
        base: base ? { version: base.version, config: base.config } : undefined,
        spans: doc.spans,
        focusedPath,
        onFocusPath: setFocusedPath,
        registry,
        readOnly: canWrite.allowed !== true,
        isCodeOwned: (path: string) =>
          doc.source.codeOwned.some((owned) => path === owned || path.startsWith(`${owned}.`)),
        onEditInCode: (path: string) => {
          setFocusedPath(path);
          if (layout === "form") setLayout("split");
        },
      }
    : undefined;
  const component = detail.component;
  const counts = diff.data?.counts;

  const header = (
    <div className="flex flex-wrap items-center gap-3 border-b border-border-subtle px-6 py-2.5">
      <Breadcrumb
        items={[
          { label: "Studio" },
          { label: FAMILY_LABEL[kind], href: `${scoped}/studio/${kind}s` },
          { label: component.id, mono: true },
        ]}
        renderLink={(crumb) => <Link to={crumb.href}>{crumb.label}</Link>}
      />
      <DraftChip doc={doc} />
      <IncomingChip instance={instance} componentId={componentId} />
      <span className="flex-1" />
      <ExplainConfig instance={instance} componentId={componentId} config={doc.config} />
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
      {draft && (
        <Button asChild variant="outline" size="32">
          <Link to={`${scoped}/evals`}>
            <CheckCircle2 aria-hidden />
            Run evals
          </Link>
        </Button>
      )}
      {draft && canWrite.allowed && (
        <Button
          variant="secondary"
          size="32"
          disabled={doc.state === "saving" || doc.state === "saved"}
          onClick={() => {
            void doc.save();
          }}
        >
          Save draft
        </Button>
      )}
      {component.current_version && canPromote.allowed && (
        <Button
          variant="outline"
          size="32"
          onClick={() => {
            setDialog("promote");
          }}
        >
          <Upload aria-hidden />
          Promote…
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
  );

  const toolbar = (
    <div className="flex flex-wrap items-center gap-3 px-6 py-2">
      <SegmentedControl
        label="Editor layout"
        value={layout}
        onValueChange={setLayout}
        options={[
          { value: "form", label: "Form", icon: <Rows3 aria-hidden /> },
          { value: "split", label: "Split", icon: <Columns2 aria-hidden /> },
          { value: "code", label: "Code", icon: <Code2 aria-hidden /> },
        ]}
      />
      <span
        className="inline-flex items-center gap-1.5 text-[12.5px] text-fg-secondary"
        onMouseEnter={() => {
          preloadCodeView();
          preloadCodeEditor();
        }}
      >
        <ArrowLeftRight aria-hidden className="size-3.5 text-accent" />
        Form and code are one source: edits in either show in the other.
      </span>
      <span className="flex-1" />
      {toolbarExtra?.(doc)}
      {base && draft && counts && counts.added + counts.changed + counts.removed > 0 && (
        <button
          type="button"
          className="inline-flex items-center gap-2 text-[12.5px] text-fg-secondary hover:text-fg"
          onClick={() => {
            setDialog("diff");
          }}
        >
          {counts.added > 0 && <span className="font-mono text-accent">{`+${String(counts.added)}`}</span>}
          {counts.changed > 0 && (
            <span className="font-mono text-modified">{`~${String(counts.changed)}`}</span>
          )}
          {counts.removed > 0 && (
            <span className="font-mono text-danger">{`−${String(counts.removed)}`}</span>
          )}
          {`View diff against v${String(base.version)}`}
        </button>
      )}
    </div>
  );

  const noDraft = !draft && (
    <Callout
      tone="info"
      title="No open draft"
      action={
        canWrite.allowed ? (
          <Button
            variant="primary"
            size="30"
            disabled={doc.startingDraft}
            onClick={() => {
              void doc.startDraft();
            }}
          >
            {`Start a draft from v${String(component.current_version ?? "")}`}
          </Button>
        ) : undefined
      }
    >
      {`The current version is v${String(component.current_version ?? "")}. Edits go into a new draft; the current version keeps serving until you publish.`}
    </Callout>
  );

  const form = ctx ? renderForm(ctx, doc) : noDraft || <EmptyState title="Nothing to edit." />;
  const code = (
    <CodePane
      code={doc.code}
      source={doc.source}
      onCode={doc.setCode}
      onGenerate={doc.generateFromForm}
      config={doc.config}
      kind={kind}
      focusedPath={focusedPath}
      onFocusPath={setFocusedPath}
      registryHref={(entry) => `${scoped}/studio/registry/tool/${encodeURIComponent(entry)}`}
      uncommitted={unpublished(base?.config, doc.config)}
      pending={doc.state === "dirty"}
      readOnly={canWrite.allowed !== true}
      sourceBar={
        <SourceBar instance={instance} componentId={componentId} canWrite={canWrite.allowed === true} />
      }
      incomingMarks={incomingMarks(source.data, draft?.version)}
    />
  );
  const test = (
    <TestPane
      instance={instance}
      instanceName={instanceName}
      componentId={component.id}
      componentName={component.name}
      kind={kind}
      draft={draft}
      currentVersion={component.current_version}
      outputSchema={outputSchema}
      canTestDraft={canWrite}
      beforeRun={doc.save}
    />
  );

  return (
    <div className="flex flex-1 flex-col">
      {header}
      {toolbar}
      {!draft && ctx === undefined && <div className="px-6">{noDraft}</div>}
      <div className="flex flex-1 flex-wrap gap-4 px-6 pb-6">
        {layout !== "code" && (
          <div
            className={cn(
              "flex min-w-[320px] flex-col gap-3",
              layout === "split" ? "max-w-[360px] flex-[1_1_320px]" : "max-w-[760px] flex-[2_1_520px]",
            )}
          >
            {form}
          </div>
        )}
        {layout !== "form" && <div className="flex min-w-[440px] flex-[2_1_440px] flex-col">{code}</div>}
        <div
          className={cn(
            "flex min-w-[300px] flex-col",
            layout === "split" ? "max-w-[380px] flex-[1_1_300px]" : "max-w-[520px] flex-[1_1_380px]",
          )}
        >
          {test}
        </div>
      </div>

      {base && draft && (
        <DiffDialog
          open={dialog === "diff"}
          onOpenChange={(open) => {
            setDialog(open ? "diff" : undefined);
          }}
          instance={instance}
          componentId={component.id}
          from={base.version}
          to={draft.version}
        />
      )}
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
      {component.current_version && (
        <PromoteDialog
          open={dialog === "promote"}
          onOpenChange={(open) => {
            setDialog(open ? "promote" : undefined);
          }}
          instance={instance}
          componentId={component.id}
          version={component.current_version}
        />
      )}
      <ConflictDialog
        open={doc.conflict !== undefined}
        savedBy={doc.conflict?.savedBy}
        savedAt={doc.conflict?.savedAt}
        onKeep={doc.resolveConflict}
      />
    </div>
  );
}
