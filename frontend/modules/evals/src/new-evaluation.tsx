import {
  describeError,
  evalsCreateDataset,
  evalsEvalCapabilitiesOptions,
  evalsImportCases,
  evalsListDatasetsOptions,
  evalsStartBatch,
  gatewayJson,
  type BatchOut,
} from "@agnostic/api";
import { useCan, useComponentVersions, useComponents } from "@agnostic/core";
import {
  Button,
  Callout,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
  RadioCards,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  toast,
} from "@agnostic/ui";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { EVAL_TYPES, TYPE_HINT, TYPE_LABEL, type EvalType } from "./labels";

const CURRENT = "current";
const DEFAULT_JUDGE = "default";

type ConfigModels = { available_models?: { id?: string | null; provider?: string | null }[] | null };

function NewDatasetDialog({
  instance,
  evalType,
  open,
  onOpenChange,
  onCreated,
}: {
  instance: string;
  evalType: EvalType;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | undefined>(undefined);
  const create = useMutation({
    mutationFn: async () => {
      const created = (
        await evalsCreateDataset({
          path: { instance },
          body: { name: name.trim(), eval_type: evalType },
          throwOnError: true,
        })
      ).data;
      if (file) {
        const content = await file.text();
        await evalsImportCases({
          path: { instance, dataset_id: created.id },
          body: { format: file.name.endsWith(".csv") ? "csv" : "jsonl", content },
          throwOnError: true,
        });
      }
      return created.id;
    },
    onSuccess: (id) => {
      onCreated(id);
      onOpenChange(false);
      setName("");
      setFile(undefined);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New {TYPE_LABEL[evalType].toLowerCase()} dataset</DialogTitle>
          <DialogDescription>
            Datasets are shared by every instance. Import cases from CSV or JSON Lines with an{" "}
            <code>input</code> column and {evalType === "accuracy" && <code>expected_output</code>}
            {evalType === "agent_as_judge" && <code>criteria</code>}
            {evalType === "reliability" && <code>expected_tool_calls</code>}
            {evalType === "performance" && "nothing else"}.
          </DialogDescription>
        </DialogHeader>
        <form
          id="new-dataset"
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <Field label="Name">
            {({ id }) => (
              <Input
                id={id}
                required
                placeholder="billing-tickets-v2"
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                }}
              />
            )}
          </Field>
          <Field label="Cases file" hint="Optional; you can import later.">
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                type="file"
                accept=".csv,.jsonl,.json,text/csv,application/x-ndjson"
                className="text-[12.5px]"
                onChange={(event) => {
                  setFile(event.target.files?.[0]);
                }}
              />
            )}
          </Field>
          {create.isError && <Callout tone="danger">{describeError(create.error).reason}</Callout>}
        </form>
        <DialogFooter>
          <Button
            variant="outline"
            size="32"
            onClick={() => {
              onOpenChange(false);
            }}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form="new-dataset"
            variant="primary"
            size="32"
            disabled={!name.trim() || create.isPending}
          >
            Create dataset
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The "New evaluation" panel: a component version, a dataset and a judge → one eval run per case. */
export function NewEvaluation({
  instance,
  onCancel,
  onStarted,
}: {
  instance: string;
  onCancel: () => void;
  onStarted: (batch: BatchOut) => void;
}) {
  const queryClient = useQueryClient();
  const canWrite = useCan("evals:write", instance);
  const agents = useComponents(instance, "agents");
  const teams = useComponents(instance, "teams");
  const components = [
    ...(agents.data ?? []).map((item) => ({ ...item, kind: "agent" as const })),
    ...(teams.data ?? []).map((item) => ({ ...item, kind: "team" as const })),
  ];
  const [componentKey, setComponentKey] = useState<string>("");
  const component = components.find((item) => `${item.kind}:${item.id}` === componentKey) ?? components[0];
  const versions = useComponentVersions(instance, component?.id, component?.isComponent ?? false);
  const [version, setVersion] = useState<string>(CURRENT);
  const [evalType, setEvalType] = useState<EvalType>("accuracy");
  const datasetOptions = evalsListDatasetsOptions({ path: { instance }, query: { eval_type: evalType } });
  const datasets = useQuery({
    ...datasetOptions,
    queryFn: instance ? (datasetOptions.queryFn ?? skipToken) : skipToken,
  });
  const [datasetId, setDatasetId] = useState<string>("");
  const dataset = datasets.data?.find((item) => item.id === datasetId) ?? datasets.data?.[0];
  const capabilityOptions = evalsEvalCapabilitiesOptions({ path: { instance } });
  const capabilities = useQuery({
    ...capabilityOptions,
    queryFn: instance ? (capabilityOptions.queryFn ?? skipToken) : skipToken,
  });
  const pinned = capabilities.data?.versions === true;
  const config = useQuery({
    queryKey: [instance, "agentos", "config-models"],
    queryFn: instance ? () => gatewayJson<ConfigModels>(instance, "config") : skipToken,
    staleTime: 300_000,
  });
  const judges = (config.data?.available_models ?? []).flatMap((model) =>
    model.id ? [{ id: model.id, provider: model.provider ?? "" }] : [],
  );
  const [judge, setJudge] = useState<string>(DEFAULT_JUDGE);
  const [creating, setCreating] = useState(false);

  const selectedVersion = versions.data?.find((item) => String(item.version) === version);
  const isDraft = selectedVersion ? selectedVersion.stage !== "published" : false;
  const start = useMutation({
    mutationFn: async () => {
      const chosen = judges.find((item) => `${item.provider}:${item.id}` === judge);
      return (
        await evalsStartBatch({
          path: { instance },
          body: {
            dataset_id: dataset?.id ?? "",
            component_kind: component?.kind ?? "agent",
            component_id: component?.id ?? "",
            version: version === CURRENT ? null : Number(version),
            judge: chosen ? { model_id: chosen.id, provider: chosen.provider } : null,
          },
          throwOnError: true,
        })
      ).data;
    },
    onSuccess: (batch) => {
      void queryClient.invalidateQueries({ queryKey: [{ _id: "evalsListEvaluations" }] });
      toast.success(`Evaluating ${batch.component_id} ${batch.version_label} on ${batch.dataset_name}`);
      onStarted(batch);
    },
  });

  const runs = dataset ? dataset.case_count : 0;
  const target = version === CURRENT ? "the current version" : isDraft ? "the draft" : `v${version}`;
  return (
    <section
      id="new-eval"
      aria-labelledby="new-eval-title"
      className="flex flex-col gap-4 rounded-panel border border-border-strong bg-surface-raised p-4 shadow-popover"
    >
      <header className="flex items-center justify-between gap-2">
        <h2 id="new-eval-title" className="text-[15px] font-semibold">
          New evaluation
        </h2>
        <span className="font-mono text-[11.5px] text-fg-muted">
          POST {pinned ? "/agnostic/v1/evals/run" : "/eval-runs"}
        </span>
      </header>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
        <Field label="Component">
          {({ id }) => (
            <Select
              value={component ? `${component.kind}:${component.id}` : ""}
              onValueChange={(value) => {
                setComponentKey(value);
                setVersion(CURRENT);
              }}
            >
              <SelectTrigger id={id} className="font-mono" title={component?.id}>
                <SelectValue placeholder="Pick a component" />
              </SelectTrigger>
              <SelectContent>
                {components.map((item) => (
                  <SelectItem key={`${item.kind}:${item.id}`} value={`${item.kind}:${item.id}`}>
                    {item.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>
        <Field label="Version">
          {({ id }) => (
            <Select value={version} onValueChange={setVersion}>
              <SelectTrigger id={id}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={CURRENT}>
                  {component?.currentVersion ? `v${String(component.currentVersion)} · current` : "current"}
                </SelectItem>
                {(versions.data ?? []).map((item) => (
                  <SelectItem key={item.version} value={String(item.version)} disabled={!pinned}>
                    v{item.version} {item.stage === "published" ? "" : "draft"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>
        <Field label="Dataset">
          {({ id }) => (
            <Select
              value={dataset?.id ?? ""}
              onValueChange={(value) => {
                if (value === "new") setCreating(true);
                else setDatasetId(value);
              }}
            >
              <SelectTrigger id={id} title={dataset?.name}>
                <SelectValue placeholder="No dataset yet" />
              </SelectTrigger>
              <SelectContent>
                {(datasets.data ?? []).map((item) => (
                  <SelectItem key={item.id} value={item.id} title={item.name}>
                    {item.name} · {item.case_count} cases
                  </SelectItem>
                ))}
                <SelectItem value="new">New dataset…</SelectItem>
              </SelectContent>
            </Select>
          )}
        </Field>
        <Field label="Judge model">
          {({ id }) => (
            <Select value={judge} onValueChange={setJudge} disabled={!pinned}>
              <SelectTrigger
                id={id}
                className="font-mono"
                title={judge === DEFAULT_JUDGE ? undefined : judge.slice(judge.indexOf(":") + 1)}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DEFAULT_JUDGE}>instance default</SelectItem>
                {judges.map((item) => (
                  <SelectItem key={`${item.provider}:${item.id}`} value={`${item.provider}:${item.id}`}>
                    {item.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>
      </div>
      <RadioCards
        legend="Eval type"
        value={evalType}
        onValueChange={(value) => {
          setEvalType(value);
          setDatasetId("");
        }}
        options={EVAL_TYPES.map((type) => ({
          value: type,
          label: TYPE_LABEL[type],
          description: TYPE_HINT[type],
        }))}
      />
      {capabilities.data && !pinned && capabilities.data.reason && (
        <Callout tone="availability">{capabilities.data.reason}</Callout>
      )}
      {start.isError && <Callout tone="danger">{describeError(start.error).reason}</Callout>}
      <footer className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-[12.5px] text-fg-muted">
          Needs <code className="font-mono">evals:write</code> · {runs} run{runs === 1 ? "" : "s"} of {target}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="32" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="32"
            disabled={canWrite.allowed !== true || !component || !dataset || runs === 0 || start.isPending}
            title={canWrite.allowed === false ? canWrite.reason : undefined}
            onClick={() => {
              start.mutate();
            }}
          >
            Run evaluation
          </Button>
        </div>
      </footer>
      <NewDatasetDialog
        instance={instance}
        evalType={evalType}
        open={creating}
        onOpenChange={setCreating}
        onCreated={(id) => {
          setDatasetId(id);
          void queryClient.invalidateQueries({ queryKey: datasetOptions.queryKey });
        }}
      />
    </section>
  );
}
