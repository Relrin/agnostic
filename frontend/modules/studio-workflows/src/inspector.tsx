// The inspector: the selected node's settings (or the workflow's, with nothing selected). Fields come from the
// workflow schema per node type and reuse the Studio form controls on a node-scoped form context; the executor,
// CEL fields and human review have their own editors. Human review shows only what the node type supports. The Runs
// tab lists the step's latest results.
import { studioStepRunsOptions } from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import {
  ConfigForm,
  FieldControl,
  isRecord,
  type FieldInfo,
  type FormContext,
  type Section,
} from "@agnostic/studio";
import {
  Badge,
  Button,
  Combobox,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  NODE_COLORS,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { Copy, Layers, Trash2, Ungroup } from "lucide-react";
import { forwardRef, useMemo } from "react";

import { CelField, type CelContext } from "./cel-field";
import { useBuilderContext } from "./context";
import { useBuilder } from "./history";
import { executorLabel, kindLabel, type ExecutorOption, type WorkflowSchema } from "./schema";
import {
  CONTAINERS,
  EXECUTOR_FIELDS,
  children,
  executorOf,
  flatten,
  nodeAt,
  nodeName,
  nodeType,
  type NodeType,
  type WorkflowNode,
} from "./tree";

const CEL_FIELDS: Partial<Record<NodeType, { field: string; context: CelContext }>> = {
  Condition: { field: "evaluator", context: "condition" },
  Loop: { field: "end_condition", context: "loop" },
  Router: { field: "selector", context: "router" },
};
const REVIEW_LABELS: Record<string, string> = {
  confirmation: "Ask before it runs",
  user_input: "Ask for input",
  route_selection: "Route selection",
  output_review: "Review the output",
  iteration_review: "Review each iteration",
  rejection: "When rejected",
  errors: "When a step fails",
  timeout: "Expiry",
};

/** Put `next`'s fields on `target` (an immer draft), removing the ones `next` dropped. */
function replaceFields(target: Record<string, unknown>, next: Record<string, unknown>): void {
  for (const key of Object.keys(target)) if (!(key in next)) Reflect.deleteProperty(target, key);
  Object.assign(target, next);
}

function scopedSpans(spans: FormContext["spans"], prefix: string): FormContext["spans"] {
  const found: FormContext["spans"] = {};
  for (const [path, span] of Object.entries(spans)) {
    if (path.startsWith(`${prefix}.`)) found[path.slice(prefix.length + 1)] = span;
  }
  return found;
}

export type InspectorProps = {
  instance: string;
  componentId: string;
  schema: WorkflowSchema;
  executors: ExecutorOption[];
  /** The workflow-level form (identity, input, history, advanced). */
  workflowForm: { sections: Section[]; fields: Record<string, FieldInfo>; ctx: FormContext | undefined };
  focusedPath: string | undefined;
  onFocusPath: (path: string | undefined) => void;
};

export const Inspector = forwardRef<HTMLElement, InspectorProps>(function Inspector(props, ref) {
  const { doc, store } = useBuilderContext();
  const selected = useBuilder(store, (state) => state.selected);
  const node = selected ? nodeAt(doc.config, selected) : undefined;
  return (
    <aside
      ref={ref}
      tabIndex={-1}
      aria-label="Step properties"
      className="flex min-h-0 w-[min(340px,40vw)] shrink-0 flex-col overflow-y-auto border-l border-border bg-surface outline-none"
    >
      {selected && node ? (
        <NodeInspector {...props} path={selected} node={node} />
      ) : props.workflowForm.ctx ? (
        <div className="flex flex-col gap-3 p-4">
          <h2 className="text-[15px] font-semibold">Workflow settings</h2>
          <p className="text-[12px] text-fg-muted">Select a step on the canvas to edit it.</p>
          <ConfigForm
            sections={props.workflowForm.sections}
            fields={props.workflowForm.fields}
            ctx={props.workflowForm.ctx}
            ariaLabel="Workflow settings"
          />
        </div>
      ) : (
        <EmptyState title="Nothing to edit" />
      )}
    </aside>
  );
});

function NodeInspector({
  instance,
  componentId,
  schema,
  executors,
  path,
  node,
  focusedPath,
  onFocusPath,
}: InspectorProps & { path: string; node: WorkflowNode }) {
  const { doc, actions, readOnly, store } = useBuilderContext();
  const type = nodeType(node);
  const order = flatten(doc.config);
  const position = order.findIndex((item) => item.path === path) + 1;
  const color = NODE_COLORS[type];

  const ctx: FormContext = useMemo(
    () => ({
      config: node,
      onChange: (update) => {
        actions.update(path, `Edit ${nodeName(node) || type}`, (draft) => {
          replaceFields(draft, update({ ...draft }));
        });
      },
      spans: scopedSpans(doc.spans, path),
      focusedPath: focusedPath?.startsWith(`${path}.`) ? focusedPath.slice(path.length + 1) : undefined,
      onFocusPath: (field) => {
        onFocusPath(field ? `${path}.${field}` : path);
      },
      registry: { byType: () => [], find: () => undefined },
      readOnly,
    }),
    [actions, doc.spans, focusedPath, node, onFocusPath, path, readOnly, type],
  );
  const functions = executors.filter((item) => item.kind === "function").map((item) => item.id);

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-2">
        <span
          className="rounded-type px-1.5 py-0.5 font-mono text-[10.5px] uppercase"
          style={{ color, backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)` }}
        >
          {type}
        </span>
        <span className="text-[11.5px] text-fg-muted">{`step ${String(position)} of ${String(order.length)}`}</span>
        <span className="flex-1" />
        <NodeMenu path={path} type={type} />
      </div>
      <h2 className="truncate text-[16px] font-semibold">{nodeName(node) || "Untitled"}</h2>
      <Tabs defaultValue="settings">
        <TabsList variant="underline">
          <TabsTrigger value="settings">Settings</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
        </TabsList>
        <TabsContent value="settings" className="flex flex-col gap-4 pt-3">
          {schema.sections[type].map((section) => (
            <section key={section.id} aria-label={section.label} className="flex flex-col gap-3">
              {section.id !== "settings" && (
                <h3 className="font-mono text-[10.5px] tracking-wide text-fg-muted uppercase">
                  {section.label}
                </h3>
              )}
              {section.id === "executor" ? (
                <ExecutorPicker path={path} node={node} executors={executors} />
              ) : section.id === "review" ? (
                <ReviewEditor path={path} node={node} type={type} schema={schema} />
              ) : (
                section.fields.map((field) => {
                  const info = schema.fields[type][field];
                  if (!info) return null;
                  const cel = CEL_FIELDS[type];
                  if (cel?.field === field) {
                    return (
                      <CelField
                        key={field}
                        id={`field-${path}-${field}`}
                        label={info.label}
                        instance={instance}
                        context={cel.context}
                        value={node[field]}
                        kind={
                          typeof node[`${field}_type`] === "string"
                            ? String(node[`${field}_type`])
                            : undefined
                        }
                        choices={type === "Router" ? children(node, "choices").map(nodeName) : undefined}
                        functions={functions}
                        readOnly={readOnly}
                        onChange={(value, kind) => {
                          actions.update(path, `Edit ${info.label.toLowerCase()}`, (draft) => {
                            draft[field] = value;
                            draft[`${field}_type`] = kind;
                          });
                        }}
                      />
                    );
                  }
                  return <FieldControl key={field} name={field} info={info} ctx={ctx} />;
                })
              )}
            </section>
          ))}
          {type === "Router" && <Choices path={path} node={node} />}
        </TabsContent>
        <TabsContent value="runs" className="pt-3">
          <StepRuns instance={instance} componentId={componentId} step={nodeName(node)} />
        </TabsContent>
      </Tabs>
      {CONTAINERS.includes(type) && (
        <p className="text-[11.5px] text-fg-muted">
          {`Its steps are on the canvas: select one to edit it. ${String(flatten({ steps: [node] }).length - 1)} inside.`}
        </p>
      )}
      <Button
        variant="ghost"
        size="28"
        className="self-start"
        onClick={() => {
          store.getState().select(undefined);
        }}
      >
        Workflow settings
      </Button>
    </div>
  );
}

function NodeMenu({ path, type }: { path: string; type: NodeType }) {
  const { actions, readOnly } = useBuilderContext();
  if (readOnly) return null;
  return (
    <div className="flex items-center gap-1">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="icon" size="28" aria-label="Wrap in a container">
            <Layers aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {(["Steps", "Parallel", "Loop", "Condition"] as const).map((wrapper) => (
            <DropdownMenuItem
              key={wrapper}
              onSelect={() => {
                actions.wrap(path, wrapper);
              }}
            >
              {`Wrap in ${wrapper}`}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      {CONTAINERS.includes(type) && type !== "Router" && (
        <Button
          variant="icon"
          size="28"
          aria-label="Unwrap: keep its steps"
          onClick={() => {
            actions.unwrap(path);
          }}
        >
          <Ungroup aria-hidden />
        </Button>
      )}
      <Button
        variant="icon"
        size="28"
        aria-label="Copy"
        onClick={() => {
          actions.copy(path);
        }}
      >
        <Copy aria-hidden />
      </Button>
      <Button
        variant="icon"
        size="28"
        aria-label="Delete"
        onClick={() => {
          actions.remove(path);
        }}
      >
        <Trash2 aria-hidden />
      </Button>
    </div>
  );
}

function ExecutorPicker({
  path,
  node,
  executors,
}: {
  path: string;
  node: WorkflowNode;
  executors: ExecutorOption[];
}) {
  const { actions, readOnly } = useBuilderContext();
  const current = executorOf(node);
  const value = current ? `${current.kind}:${current.id}` : undefined;
  const options = executors.map((item) => ({
    value: `${item.kind}:${item.id}`,
    label: item.id,
    hint: item.source === "studio" ? `${kindLabel(item.kind)} · Studio` : kindLabel(item.kind),
    keywords: [item.label, item.kind],
  }));
  if (current && !options.some((option) => option.value === value)) {
    options.unshift({
      value: value ?? "",
      label: current.id,
      hint: `${kindLabel(current.kind)} · not on this instance`,
      keywords: [],
    });
  }
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={`executor-${path}`} className="text-[12.5px] font-medium text-fg-secondary">
        Runs
      </label>
      <Combobox
        id={`executor-${path}`}
        aria-label="Executor"
        mono
        value={value}
        placeholder="Pick an agent, team, workflow or function"
        options={options}
        disabled={readOnly}
        onValueChange={(next) => {
          const [kind, ...rest] = next.split(":");
          const chosen = executors.find((item) => item.kind === kind && item.id === rest.join(":"));
          if (!chosen) return;
          actions.update(path, "Change the executor", (draft) => {
            for (const field of Object.values(EXECUTOR_FIELDS)) Reflect.deleteProperty(draft, field);
            draft[EXECUTOR_FIELDS[chosen.kind]] = chosen.id;
          });
        }}
      />
      {current && <span className="font-mono text-[11.5px] text-fg-muted">{executorLabel(current)}</span>}
    </div>
  );
}

function ReviewEditor({
  path,
  node,
  type,
  schema,
}: {
  path: string;
  node: WorkflowNode;
  type: NodeType;
  schema: WorkflowSchema;
}) {
  const { actions, readOnly, doc } = useBuilderContext();
  const review = isRecord(node.human_review) ? node.human_review : {};
  const groups = schema.support[type] ?? [];
  const ctx: FormContext = {
    config: review,
    onChange: (update) => {
      actions.update(path, "Edit the human review", (draft) => {
        const current = isRecord(draft.human_review) ? { ...draft.human_review } : {};
        draft.human_review = update(current);
      });
    },
    spans: scopedSpans(doc.spans, `${path}.human_review`),
    focusedPath: undefined,
    onFocusPath: () => undefined,
    registry: { byType: () => [], find: () => undefined },
    readOnly,
  };
  if (groups.length === 0) {
    return (
      <p className="text-[12px] text-fg-muted">
        Steps in a Parallel run at once, so a Parallel can't pause for a person.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {groups.map((group) => (
        <fieldset key={group} className="flex flex-col gap-2 rounded-control border border-border-subtle p-3">
          <legend className="px-1 text-[12px] font-medium text-fg-secondary">
            {REVIEW_LABELS[group] ?? group}
          </legend>
          {(schema.groups[group] ?? []).map((field) => {
            const info = schema.review[field];
            return info ? <FieldControl key={field} name={field} info={info} ctx={ctx} /> : null;
          })}
        </fieldset>
      ))}
    </div>
  );
}

function Choices({ path, node }: { path: string; node: WorkflowNode }) {
  const { actions, readOnly, store } = useBuilderContext();
  const choices = children(node, "choices");
  return (
    <section aria-label="Choices" className="flex flex-col gap-2">
      <h3 className="font-mono text-[10.5px] tracking-wide text-fg-muted uppercase">Choices</h3>
      <ul className="flex flex-col gap-1">
        {choices.map((choice, index) => {
          const type = nodeType(choice);
          const inner = children(choice, "steps").length;
          const executor = executorOf(choice);
          return (
            <li key={`${nodeName(choice)}-${String(index)}`}>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left hover:bg-surface-hover"
                onClick={() => {
                  store.getState().select(`${path}.choices[${String(index)}]`);
                }}
              >
                <span
                  aria-hidden
                  className="size-2.5 rounded-[2px]"
                  style={{ backgroundColor: NODE_COLORS[type] }}
                />
                <span className="flex-1 truncate text-[13px]">{nodeName(choice) || "Untitled"}</span>
                <span className="text-[11.5px] text-fg-muted">
                  {type === "Step"
                    ? `Step · ${executor?.id ?? "no executor"}`
                    : `${type} · ${String(inner)} steps`}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {!readOnly && (
        <Button
          variant="dashed-add"
          size="28"
          onClick={() => {
            actions.add({ parent: path, lane: "choices", index: choices.length }, "Step");
          }}
        >
          Add a choice
        </Button>
      )}
    </section>
  );
}

function StepRuns({ instance, componentId, step }: { instance: string; componentId: string; step: string }) {
  const runs = useQuery({
    ...withQueryFn(studioStepRunsOptions({ path: { instance, component_id: componentId }, query: { step } })),
    enabled: Boolean(step),
    staleTime: 30_000,
  });
  if (!step) return <p className="text-[12px] text-fg-muted">Name the step to see its runs.</p>;
  if (runs.isPending) return <p className="text-[12px] text-fg-muted">Loading runs…</p>;
  const items = runs.data ?? [];
  if (items.length === 0) return <p className="text-[12px] text-fg-muted">No runs of this step yet.</p>;
  return (
    <ul className="flex flex-col gap-2" aria-label={`Recent results of ${step}`}>
      {items.map((run) => (
        <li
          key={`${run.run_id}-${run.session_id}`}
          className="flex flex-col gap-1 rounded-control border border-border-subtle p-2"
        >
          <span className="flex items-center gap-2 text-[11.5px] text-fg-muted">
            <span className="font-mono">{run.run_id}</span>
            <span className="flex-1" />
            {run.success === false ? (
              <Badge tone="danger">failed</Badge>
            ) : (
              run.status && <Badge>{run.status.toLowerCase()}</Badge>
            )}
          </span>
          {run.content && <p className="line-clamp-4 text-[12.5px] whitespace-pre-wrap">{run.content}</p>}
          {run.error && <p className="text-[12px] text-danger">{run.error}</p>}
        </li>
      ))}
    </ul>
  );
}
