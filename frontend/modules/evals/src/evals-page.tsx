import { describeError, evalsListEvaluationsOptions, type EvaluationOut } from "@agnostic/api";
import { findInstance, formatWhen, useInstances } from "@agnostic/core";
import {
  Button,
  Callout,
  EmptyState,
  EntitySquare,
  ErrorState,
  LoadingRows,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  cn,
} from "@agnostic/ui";
import { skipToken, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Play } from "lucide-react";
import { useState } from "react";

import { EvaluationDetail } from "./evaluation-detail";
import { EVAL_TYPES, TYPE_LABEL, type EvalType } from "./labels";
import { NewEvaluation } from "./new-evaluation";

const ANY = "any";

function EvaluationRow({
  row,
  selected,
  onSelect,
}: {
  row: EvaluationOut;
  selected: boolean;
  onSelect: () => void;
}) {
  const running = row.status === "queued" || row.status === "running";
  const kind =
    row.component_kind === "team" ? "team" : row.component_kind === "workflow" ? "workflow" : "agent";
  return (
    <tr
      aria-selected={selected}
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter") onSelect();
      }}
      className={cn(
        "cursor-pointer border-b border-divider-row last:border-0 hover:bg-surface-hover",
        selected && "bg-row-selected shadow-[inset_2px_0_0_var(--accent)]",
      )}
    >
      <td className="px-3 py-2 align-top">
        <div className="font-medium">{row.name}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-fg-muted">
          {row.component_id && <EntitySquare kind={kind} />}
          {[row.component_id, row.version_label].filter(Boolean).join(" ")}
          {row.model && ` · ${row.judge ? "judge " : ""}${row.model}`}
          {row.source === "agentos" && " · run outside Agnostic"}
        </div>
      </td>
      <td className="px-2 py-2 align-top text-[12.5px]">{TYPE_LABEL[row.eval_type]}</td>
      <td className={cn("px-2 py-2 align-top tabular-nums", row.bad && "font-semibold text-danger")}>
        {running ? `${String(Math.round(row.progress * 100))}%` : row.result}
      </td>
      <td className="px-3 py-2 align-top text-[12px] text-fg-muted">
        {formatWhen(row.created_at).split(" ")[0]}
      </td>
    </tr>
  );
}

/** `/i/:instance/evals`: evaluation runs, new batches over a dataset, version comparison and the publish gate. */
export function EvalsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const raw = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instanceRef = params.instance ?? "";
  const selectedId = typeof raw.evaluation === "string" ? raw.evaluation : undefined;
  const instances = useInstances();
  const instance = findInstance(instances.data, instanceRef);
  const [evalType, setEvalType] = useState<EvalType | "all">("all");
  const [component, setComponent] = useState<string>(ANY);
  const [model, setModel] = useState<string>(ANY);
  const [creating, setCreating] = useState(false);

  const options = evalsListEvaluationsOptions({
    path: { instance: instanceRef },
    query: {
      ...(evalType !== "all" ? { eval_type: evalType } : {}),
      ...(component !== ANY ? { component_id: component } : {}),
      ...(model !== ANY ? { model } : {}),
    },
  });
  const list = useQuery({
    ...options,
    queryFn: instanceRef ? (options.queryFn ?? skipToken) : skipToken,
    refetchInterval: (query) =>
      query.state.data?.data.some((row) => row.status === "queued" || row.status === "running")
        ? 2_000
        : false,
  });
  const rows = list.data?.data ?? [];
  const components = [...new Set(rows.flatMap((row) => (row.component_id ? [row.component_id] : [])))].sort();
  const models = [...new Set(rows.flatMap((row) => (row.model ? [row.model] : [])))].sort();
  const selected = rows.find((row) => row.id === selectedId);
  const select = (id: string | undefined) => {
    void navigate({
      to: `/i/${encodeURIComponent(instanceRef)}/evals`,
      search: id ? { evaluation: id } : {},
    });
  };

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex items-center justify-end border-b border-border-subtle px-6 py-2.5">
        <Button
          variant="primary"
          size="32"
          onClick={() => {
            setCreating(true);
            requestAnimationFrame(() => {
              const panel = document.getElementById("new-eval");
              // jsdom has no scrollIntoView.
              if (panel && typeof panel.scrollIntoView === "function")
                panel.scrollIntoView({ behavior: "smooth" });
            });
          }}
        >
          <Play aria-hidden />
          Run evaluation
        </Button>
      </div>
      <div className="flex flex-1 flex-wrap gap-6 px-6 py-5">
        <div className="flex min-w-[320px] flex-[2_1_420px] flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="text-[22px] font-semibold tracking-tight">Evaluations</h1>
            <p className="text-[13px] text-fg-secondary">
              Eval runs stored by {instance?.display_name ?? instanceRef} (
              <code className="font-mono">GET /eval-runs</code>) and dataset evaluations started here.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl
              label="Eval type"
              value={evalType}
              onValueChange={setEvalType}
              options={[
                { value: "all", label: "All" },
                ...EVAL_TYPES.map((type) => ({ value: type, label: TYPE_LABEL[type] })),
              ]}
            />
            <Select value={component} onValueChange={setComponent}>
              <SelectTrigger aria-label="Component" className="h-8 w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Component: Any</SelectItem>
                {components.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger aria-label="Model" className="h-8 w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Model: Any</SelectItem>
                {models.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="overflow-hidden rounded-card border border-border bg-surface">
            <table className="w-full border-collapse text-[13px]" aria-label="Eval runs">
              <thead>
                <tr className="border-b border-border-subtle text-left font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase">
                  <th scope="col" className="px-3 py-2 font-normal">
                    Eval
                  </th>
                  <th scope="col" className="px-2 py-2 font-normal">
                    Type
                  </th>
                  <th scope="col" className="px-2 py-2 font-normal">
                    Result
                  </th>
                  <th scope="col" className="px-3 py-2 font-normal">
                    Date
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <EvaluationRow
                    key={`${row.source}:${row.id}`}
                    row={row}
                    selected={row.id === selectedId}
                    onSelect={() => {
                      select(row.id);
                    }}
                  />
                ))}
              </tbody>
            </table>
            {list.isPending && (
              <div className="p-3">
                <LoadingRows rows={5} label="Loading evaluations" />
              </div>
            )}
            {list.isError && (
              <div className="p-3">
                <ErrorState
                  {...describeError(list.error)}
                  onRetry={() => {
                    void list.refetch();
                  }}
                />
              </div>
            )}
            {list.isSuccess && rows.length === 0 && (
              <div className="p-4">
                <EmptyState title="No evaluations yet">
                  Run one to score a version against a dataset, case by case.
                </EmptyState>
              </div>
            )}
          </div>
          {list.data?.standalone_unavailable && (
            <p className="text-[12px] text-fg-muted">
              Eval runs made outside Agnostic aren&apos;t listed: {list.data.standalone_unavailable}
            </p>
          )}
          {creating && (
            <NewEvaluation
              instance={instanceRef}
              onCancel={() => {
                setCreating(false);
              }}
              onStarted={(batch) => {
                setCreating(false);
                select(batch.id);
              }}
            />
          )}
        </div>
        <div className="flex min-w-[360px] flex-[3_1_600px] flex-col">
          {selected?.source === "agentos" ? (
            <Callout tone="info" title={selected.name}>
              {TYPE_LABEL[selected.eval_type]} · {selected.result}. This eval run was made outside Agnostic
              (an agno script, another control plane), so it has no dataset to compare case by case.
            </Callout>
          ) : selectedId ? (
            <EvaluationDetail key={selectedId} instance={instanceRef} batchId={selectedId} />
          ) : (
            <EmptyState title="Pick an evaluation">
              Compare versions case by case, and gate Studio&apos;s Publish on a minimum score.
            </EmptyState>
          )}
        </div>
      </div>
    </div>
  );
}
