import {
  describeError,
  evalsCompareBatchesOptions,
  evalsGetBatchOptions,
  evalsListGatesOptions,
  evalsPutGate,
  type BatchOut,
  type CaseChangeOut,
  type GateOut,
  type ItemOut,
  type SummaryOut,
} from "@agnostic/api";
import { formatWhen, useCan, useDebouncedCallback } from "@agnostic/core";
import {
  Badge,
  Callout,
  ErrorState,
  Input,
  LoadingRows,
  SegmentedControl,
  Switch,
  cn,
  toast,
} from "@agnostic/ui";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { LOW_SCORE, TYPE_LABEL, casesNote, scoreText } from "./labels";

type Mode = "this" | "baseline" | "compare";

function StatsTable({
  rows,
  regressed,
}: {
  rows: readonly { label: string; summary: SummaryOut | null | undefined }[];
  regressed?: string | undefined;
}) {
  return (
    <table className="w-full text-[12.5px]" aria-label="Score statistics">
      <thead>
        <tr className="font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase">
          {["Version", "# Runs", "Avg", "Mean", "Min", "Max", "Std dev"].map((title) => (
            <th
              key={title}
              scope="col"
              className={cn("py-1 font-normal", title === "Version" ? "text-left" : "text-right")}
            >
              {title}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ label, summary }) => (
          <tr key={label} className="border-t border-divider-row tabular-nums">
            <td className="py-1.5">{label}</td>
            <td className="py-1.5 text-right">{summary?.completed ?? 0}</td>
            <td
              className={cn(
                "py-1.5 text-right text-[17px] font-semibold",
                regressed === label && "text-danger",
              )}
            >
              {summary?.avg?.toFixed(2) ?? "—"}
            </td>
            <td className="py-1.5 text-right">{summary?.mean?.toFixed(2) ?? "—"}</td>
            <td className="py-1.5 text-right">{scoreText(summary?.min)}</td>
            <td className="py-1.5 text-right">{scoreText(summary?.max)}</td>
            <td className="py-1.5 text-right">{summary?.std_dev?.toFixed(2) ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function low(item: ItemOut | null | undefined): boolean {
  return item?.score !== null && item?.score !== undefined && item.score < LOW_SCORE;
}

function CaseTable({
  rows,
  actualLabel,
  compare,
}: {
  rows: readonly {
    position: number;
    input: string;
    expected: string | null;
    before?: ItemOut | null;
    after: ItemOut | null;
    change?: CaseChangeOut["change"];
  }[];
  actualLabel: string;
  compare: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-[12.5px]" aria-label="Cases">
        <thead>
          <tr className="font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase">
            {["#", "Input", "Expected", `Actual · ${actualLabel}`, "Score", "Judge's reason"].map((title) => (
              <th key={title} scope="col" className="px-2 py-1.5 text-left font-normal">
                {title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const item = row.after;
            const bad = low(item) || item?.passed === false || item?.status === "error";
            const changed = compare && row.before && row.before.score !== item?.score;
            return (
              <tr
                key={row.position}
                className={cn(
                  "border-t border-divider-row align-top",
                  bad && "bg-danger/5 shadow-[inset_2px_0_0_var(--danger)]",
                )}
              >
                <td className="px-2 py-2 text-fg-muted">{row.position}</td>
                <td className="px-2 py-2">{row.input}</td>
                <td className="px-2 py-2 text-fg-secondary">{row.expected ?? "—"}</td>
                <td className="px-2 py-2 text-fg-prose">{item?.actual ?? item?.error ?? "—"}</td>
                <td
                  className={cn(
                    "px-2 py-2 font-mono font-semibold whitespace-nowrap",
                    bad && "text-danger",
                    compare && row.change === "fix" && "text-accent",
                  )}
                >
                  {changed
                    ? `${scoreText(row.before?.score)} → ${scoreText(item?.score)}`
                    : item?.status === "error"
                      ? "error"
                      : item && item.passed !== null && item.score === null
                        ? item.passed
                          ? "pass"
                          : "fail"
                        : scoreText(item?.score)}
                </td>
                <td className="px-2 py-2 text-fg-secondary">{item?.reason ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PublishGate({ instance, batch }: { instance: string; batch: BatchOut }) {
  const queryClient = useQueryClient();
  const can = useCan("evals:gates:write", instance);
  const options = evalsListGatesOptions({ path: { instance }, query: { component_id: batch.component_id } });
  const gates = useQuery({ ...options, queryFn: options.queryFn ?? skipToken });
  const gate: GateOut | undefined = gates.data?.find(
    (item) => item.dataset_id === batch.dataset_id && item.eval_type === batch.eval_type,
  );
  const [typed, setMinimum] = useState<string | undefined>(undefined);
  const minimum = typed ?? String(gate?.min_average ?? 8.5);
  const save = useMutation({
    mutationFn: async (next: { enabled: boolean; min: number }) =>
      (
        await evalsPutGate({
          path: { instance },
          body: {
            component_kind: batch.component_kind,
            component_id: batch.component_id,
            dataset_id: batch.dataset_id,
            min_average: next.min,
            enabled: next.enabled,
          },
          throwOnError: true,
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: options.queryKey });
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const saveMinimum = useDebouncedCallback((value: number) => {
    save.mutate({ enabled: gate?.enabled ?? false, min: value });
  }, 600);
  const enabled = gate?.enabled ?? false;
  return (
    <section
      aria-labelledby="gate-title"
      className={cn(
        "flex flex-col gap-3 rounded-card border p-4",
        enabled ? "border-accent/45" : "border-border",
      )}
    >
      <Switch
        checked={enabled}
        disabled={can.allowed !== true || save.isPending}
        onCheckedChange={(checked) => {
          save.mutate({ enabled: checked, min: Number(minimum) || 0 });
        }}
        label={<span id="gate-title">Gate publish on this eval</span>}
        description={
          <>
            Studio blocks <strong>Publish</strong> for {batch.component_id} while the average on{" "}
            {batch.dataset_name} is below the threshold.
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="gate-minimum" className="text-[12.5px] text-fg-secondary">
          Minimum average
        </label>
        <Input
          id="gate-minimum"
          type="number"
          min={0}
          max={10}
          step={0.1}
          className="h-8 w-[70px] font-mono"
          value={minimum}
          disabled={can.allowed !== true}
          onChange={(event) => {
            setMinimum(event.target.value);
            const value = Number(event.target.value);
            if (Number.isFinite(value) && value >= 0 && value <= 10) saveMinimum(value);
          }}
        />
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-[12.5px]",
            gate?.state === "would_block" || gate?.state === "no_result" ? "text-warning" : "text-fg-muted",
            gate?.state === "passes" && "text-accent",
          )}
          aria-live="polite"
        >
          <span aria-hidden className="size-1.5 rounded-full bg-current" />
          {gate?.consequence ?? "Off: Publish ignores this eval."}
        </span>
      </div>
      <p className="text-[12px] text-fg-muted">
        Owners and Administrators can override with a reason; overrides go to the audit log.
        {can.allowed === false && " Changing the gate needs evals:gates:write."}
      </p>
    </section>
  );
}

/** One evaluation: statistics, cases (alone or against another version), the insight and the publish gate. */
export function EvaluationDetail({ instance, batchId }: { instance: string; batchId: string }) {
  const options = evalsGetBatchOptions({ path: { instance, batch_id: batchId } });
  const detail = useQuery({
    ...options,
    queryFn: options.queryFn ?? skipToken,
    refetchInterval: (query) => {
      const status = query.state.data?.batch.status;
      return status === "queued" || status === "running" ? 1_500 : false;
    },
  });
  const baseline = detail.data?.baseline;
  const [mode, setMode] = useState<Mode>("compare");
  const compareOptions = evalsCompareBatchesOptions({
    path: { instance, batch_id: batchId },
    query: { with: baseline?.id ?? "" },
  });
  const comparison = useQuery({
    ...compareOptions,
    queryFn:
      baseline && detail.data?.batch.status === "completed"
        ? (compareOptions.queryFn ?? skipToken)
        : skipToken,
  });

  if (detail.isPending) return <LoadingRows rows={6} label="Loading evaluation" />;
  if (detail.isError)
    return (
      <ErrorState
        {...describeError(detail.error)}
        onRetry={() => {
          void detail.refetch();
        }}
      />
    );
  const { batch, items } = detail.data;
  const running = batch.status === "queued" || batch.status === "running";
  const effective: Mode = baseline ? mode : "this";
  const compared = comparison.data;
  const scoreRows =
    effective === "compare" && compared
      ? compared.rows.map((row) => ({ ...row, after: row.after ?? null }))
      : effective === "baseline" && compared
        ? compared.rows.map((row) => ({ ...row, after: row.before ?? null }))
        : items.map((item) => ({
            position: item.position,
            input: item.input,
            expected: item.expected,
            after: item,
          }));
  const label = effective === "baseline" && baseline ? baseline.version_label : batch.version_label;
  const regressed =
    compared && (compared.after.summary?.avg ?? 0) < (compared.before.summary?.avg ?? 0)
      ? compared.after.version_label
      : undefined;
  const statsRows =
    effective === "compare" && compared
      ? [
          { label: compared.before.version_label, summary: compared.before.summary },
          { label: compared.after.version_label, summary: compared.after.summary },
        ]
      : effective === "baseline" && baseline
        ? [{ label: baseline.version_label, summary: baseline.summary }]
        : [{ label: batch.version_label, summary: batch.summary }];
  const note =
    effective === "compare" && compared
      ? casesNote(
          scoreRows.length,
          batch.case_count,
          { before: compared.before.version_label, after: compared.after.version_label },
          { before: compared.counts.below_before, after: compared.counts.below_after },
        )
      : casesNote(
          scoreRows.length,
          batch.case_count,
          { after: label },
          { after: scoreRows.filter((row) => low(row.after)).length },
        );
  const scoped = `/i/${encodeURIComponent(instance)}`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <h2 className="text-[19px] font-semibold">{batch.name}</h2>
        <div className="flex flex-wrap gap-1.5">
          <Badge tone="outline">{TYPE_LABEL[batch.eval_type]}</Badge>
          <Badge tone="outline">
            {batch.dataset_name} · {batch.case_count} cases
          </Badge>
          <Badge tone="outline" className="normal-case">
            judge {batch.judge?.model_id ?? "instance default"}
          </Badge>
          <Badge tone="outline" className="normal-case">
            run by {batch.started_by_name} · {formatWhen(batch.started_at)}
          </Badge>
        </div>
      </div>

      {running && (
        <div className="flex flex-col gap-1.5" aria-live="polite">
          <span className="text-[12.5px] text-fg-secondary">
            {batch.status === "queued" ? "Queued" : "Running"}:{" "}
            {Math.round(batch.progress * batch.case_count)} of {batch.case_count} cases
          </span>
          <div
            className="h-1.5 rounded-bar bg-track"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(batch.progress * 100)}
            aria-label="Evaluation progress"
          >
            <div
              className="h-full rounded-bar bg-accent"
              style={{ width: `${String(Math.round(batch.progress * 100))}%` }}
            />
          </div>
        </div>
      )}
      {batch.error && <Callout tone="danger">{batch.error}</Callout>}

      {baseline && (
        <SegmentedControl
          label="Version"
          value={mode}
          onValueChange={setMode}
          options={[
            { value: "this", label: batch.version_label },
            { value: "baseline", label: baseline.version_label },
            { value: "compare", label: "Compare" },
          ]}
        />
      )}
      <StatsTable rows={statsRows} regressed={regressed} />

      <div className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="text-[13.5px] font-semibold">Cases</h3>
          <span className="text-[12px] text-fg-muted">{note}</span>
        </div>
        <CaseTable rows={scoreRows} actualLabel={label} compare={effective === "compare"} />
      </div>

      {compared && effective === "compare" && (
        <Callout
          tone="insight"
          action={
            <span className="flex gap-3 text-[12.5px]">
              {batch.version !== null && (
                <Link
                  to={`${scoped}/studio/${batch.component_kind}s/${encodeURIComponent(batch.component_id)}`}
                  className="text-info hover:text-info-hover"
                >
                  Open {batch.version_label} in Studio
                </Link>
              )}
              <Link
                to={`${scoped}/traces?component=${batch.component_kind}:${encodeURIComponent(batch.component_id)}&status=ERROR`}
                className="text-info hover:text-info-hover"
              >
                Traces of failing cases
              </Link>
            </span>
          }
        >
          {compared.insight}
        </Callout>
      )}

      {batch.eval_type !== "performance" && <PublishGate instance={instance} batch={batch} />}
    </div>
  );
}
