// Studio › Agents / Teams / Workflows: what is stored in Studio and what is defined in code, with the live version,
// the open draft and the owner; "New" starts from blank, a template, a duplicate or imported JSON.
import {
  describeError,
  studioCreateComponent,
  studioListComponentsOptions,
  studioTemplatesOptions,
  type ComponentRowOut,
} from "@agnostic/api";
import { findInstance, formatWhen, useCan, useInstances, withQueryFn } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  EntitySquare,
  ErrorState,
  Input,
  LoadingRows,
  RadioCards,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  cn,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useState } from "react";

import { isRecord, type EditableKind } from "./config";
import { useRegistry } from "./document";

type Kind = "agent" | "team" | "workflow";
type Mode = "blank" | "template" | "duplicate" | "import";
type SourceFilter = "all" | "studio" | "code";

const TITLES: Record<Kind, { title: string; noun: string; blurb: string }> = {
  agent: {
    title: "Agents",
    noun: "agent",
    blurb:
      "Agents stored in Studio are versioned on the instance; agents defined in code are listed read-only.",
  },
  team: {
    title: "Agent teams",
    noun: "team",
    blurb: "Teams stored in Studio pin their members' versions; teams defined in code are listed read-only.",
  },
  workflow: {
    title: "Workflows",
    noun: "workflow",
    blurb: "Workflows on this instance, with their live version and open drafts.",
  },
};

function NewComponentDialog({
  instance,
  kind,
  rows,
  open,
  onOpenChange,
}: {
  instance: string;
  kind: EditableKind;
  rows: readonly ComponentRowOut[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const registry = useRegistry(instance);
  const templates = useQuery({ ...withQueryFn(studioTemplatesOptions({ query: { kind } })), enabled: open });
  const [mode, setMode] = useState<Mode>("blank");
  const [name, setName] = useState("");
  const [model, setModel] = useState<string | undefined>(undefined);
  const [templateId, setTemplateId] = useState<string | undefined>(undefined);
  const [source, setSource] = useState<string | undefined>(undefined);
  const [json, setJson] = useState("");
  const models = registry.byType("model").filter((entry) => entry.studio_available);
  const stored = rows.filter((row) => row.component.source === "studio");
  let imported: Record<string, unknown> | undefined;
  let importError: string | undefined;
  if (mode === "import" && json.trim()) {
    try {
      const parsed: unknown = JSON.parse(json);
      if (isRecord(parsed)) imported = parsed;
      else importError = "The config must be a JSON object.";
    } catch {
      importError = "That isn't valid JSON.";
    }
  }
  const chosenModel = models.find((entry) => entry.name === (model ?? models[0]?.name));
  const create = useMutation({
    mutationFn: async () =>
      (
        await studioCreateComponent({
          path: { instance },
          body: {
            kind,
            name: name.trim(),
            mode,
            template_id: mode === "template" ? (templateId ?? templates.data?.[0]?.id ?? null) : null,
            source_id: mode === "duplicate" ? (source ?? stored[0]?.component.id ?? null) : null,
            config: mode === "import" ? (imported ?? null) : null,
            model:
              mode === "blank" || mode === "template"
                ? ((chosenModel?.config_value as Record<string, unknown> | undefined) ?? null)
                : null,
          },
          throwOnError: true,
        })
      ).data,
    onSuccess: (created) => {
      toast.success(`${created.component.name} is ready as draft v${String(created.draft?.version ?? 1)}.`);
      onOpenChange(false);
      void navigate({
        to: `/i/${encodeURIComponent(instance)}/studio/${kind}s/${encodeURIComponent(created.component.id)}`,
      });
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const ready =
    name.trim().length > 0 &&
    (mode !== "import" || imported !== undefined) &&
    (mode !== "duplicate" || stored.length > 0);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{`New ${TITLES[kind].noun}`}</DialogTitle>
          <DialogDescription>
            It starts as draft v1, built from objects in this instance&apos;s registry only.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <label htmlFor="new-component-name" className="flex flex-col gap-1 text-[12.5px] text-fg-secondary">
            Name
            <Input
              id="new-component-name"
              value={name}
              placeholder={kind === "team" ? "research-team" : "support-triage"}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </label>
          <RadioCards
            legend="Start from"
            value={mode}
            onValueChange={setMode}
            options={[
              { value: "blank", label: "Blank", description: "A model and nothing else." },
              { value: "template", label: "Template", description: "A starting point to adapt." },
              { value: "duplicate", label: "Duplicate", description: `Copy another ${TITLES[kind].noun}.` },
              { value: "import", label: "Import JSON", description: "A config in agno's to_dict shape." },
            ]}
          />
          {(mode === "blank" || mode === "template") && (
            <Select value={chosenModel?.name ?? ""} onValueChange={setModel}>
              <SelectTrigger aria-label="Model · from Registry" className="h-8 font-mono">
                <SelectValue placeholder="No model registered" />
              </SelectTrigger>
              <SelectContent>
                {models.map((entry) => (
                  <SelectItem key={entry.name} value={entry.name}>
                    {entry.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {mode === "template" && (
            <Select value={templateId ?? templates.data?.[0]?.id ?? ""} onValueChange={setTemplateId}>
              <SelectTrigger aria-label="Template" className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(templates.data ?? []).map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {`${item.label} — ${item.description}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {mode === "duplicate" &&
            (stored.length ? (
              <Select value={source ?? stored[0]?.component.id ?? ""} onValueChange={setSource}>
                <SelectTrigger aria-label={`${TITLES[kind].noun} to duplicate`} className="h-8 font-mono">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {stored.map((row) => (
                    <SelectItem key={row.component.id} value={row.component.id}>
                      {row.component.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Callout tone="info">{`There is no ${TITLES[kind].noun} stored in Studio to duplicate yet.`}</Callout>
            ))}
          {mode === "import" && (
            <>
              <Textarea
                aria-label="Config JSON"
                rows={8}
                className="font-mono text-[12px]"
                placeholder='{"model": {"id": "…", "provider": "…"}, "instructions": ["…"]}'
                value={json}
                onChange={(event) => {
                  setJson(event.target.value);
                }}
              />
              {importError && <p className="text-[12px] text-danger">{importError}</p>}
            </>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="primary"
            disabled={!ready || create.isPending}
            onClick={() => {
              create.mutate();
            }}
          >
            {`Create ${TITLES[kind].noun}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ComponentIndex({ instance, kind }: { instance: string; kind: Kind }) {
  const instances = useInstances();
  const found = findInstance(instances.data, instance);
  const canWrite = useCan("components:write", instance);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<SourceFilter>("all");
  const [creating, setCreating] = useState(false);
  const list = useQuery(withQueryFn(studioListComponentsOptions({ path: { instance }, query: { kind } })));
  const scoped = `/i/${encodeURIComponent(instance)}`;
  const needle = query.trim().toLowerCase();
  const rows = (list.data ?? []).filter(
    (row) =>
      (source === "all" || row.component.source === source) &&
      (!needle ||
        row.component.id.toLowerCase().includes(needle) ||
        row.component.name.toLowerCase().includes(needle)),
  );
  const editable = kind !== "workflow";
  return (
    <div className="flex flex-1 flex-col gap-4 px-6 py-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex flex-1 flex-col gap-1">
          <h1 className="text-[22px] font-semibold tracking-tight">{TITLES[kind].title}</h1>
          <p className="text-[13px] text-fg-secondary">
            {`${TITLES[kind].blurb} On ${found?.display_name ?? instance}.`}
          </p>
        </div>
        {editable && canWrite.allowed && (
          <Button
            variant="primary"
            size="32"
            onClick={() => {
              setCreating(true);
            }}
          >
            <Plus aria-hidden />
            {`New ${TITLES[kind].noun}`}
          </Button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Filter by name"
          placeholder="Filter by name"
          className="h-8 w-60"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
        <Select
          value={source}
          onValueChange={(next) => {
            setSource(next as SourceFilter);
          }}
        >
          <SelectTrigger aria-label="Source" className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Source: All</SelectItem>
            <SelectItem value="studio">Source: Studio</SelectItem>
            <SelectItem value="code">Source: Code</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-[12.5px] text-fg-muted">{`${String(rows.length)} of ${String(list.data?.length ?? 0)}`}</span>
      </div>
      <div className="overflow-hidden rounded-card border border-border bg-surface">
        <table className="w-full border-collapse text-[13px]" aria-label={TITLES[kind].title}>
          <thead>
            <tr className="border-b border-border-subtle text-left font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase">
              <th scope="col" className="px-3 py-2 font-normal">
                Name
              </th>
              <th scope="col" className="px-2 py-2 font-normal">
                Live
              </th>
              <th scope="col" className="px-2 py-2 font-normal">
                Draft
              </th>
              <th scope="col" className="px-2 py-2 font-normal">
                Source
              </th>
              <th scope="col" className="px-2 py-2 font-normal">
                Runs 7d
              </th>
              <th scope="col" className="px-3 py-2 font-normal">
                Last edited
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const href = `${scoped}/studio/${kind}s/${encodeURIComponent(row.component.id)}`;
              const linked = editable && row.editable && row.component.source === "studio";
              return (
                <tr
                  key={row.component.id}
                  className="border-b border-divider-row last:border-0 hover:bg-surface-hover"
                >
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <EntitySquare kind={kind} />
                      {linked ? (
                        <Link to={href} className="font-medium hover:underline">
                          {row.component.name}
                        </Link>
                      ) : (
                        <span className="font-medium">{row.component.name}</span>
                      )}
                    </div>
                    <div className="mt-0.5 font-mono text-[11.5px] text-fg-muted">{row.component.id}</div>
                  </td>
                  <td className="px-2 py-2 font-mono text-[12.5px]">
                    {row.component.current_version ? `v${String(row.component.current_version)}` : "—"}
                  </td>
                  <td className="px-2 py-2 text-[12.5px]">
                    {row.draft_version ? (
                      <span className="text-warning">{`v${String(row.draft_version)} draft`}</span>
                    ) : (
                      <span className="text-fg-muted">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {row.component.source === "code" ? (
                      <Badge tone="outline">Defined in code</Badge>
                    ) : (
                      <Badge tone="info">Studio</Badge>
                    )}
                  </td>
                  <td className="px-2 py-2 text-[12.5px] text-fg-muted tabular-nums">
                    {row.runs_7d === null || row.runs_7d === undefined ? "—" : String(row.runs_7d)}
                  </td>
                  <td className={cn("px-3 py-2 text-[12px] text-fg-muted")}>
                    {formatWhen(row.draft_updated_at ?? row.component.updated_at ?? row.component.created_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {list.isPending && (
          <div className="p-3">
            <LoadingRows rows={4} label={`Loading ${TITLES[kind].title.toLowerCase()}`} />
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
            <EmptyState
              title={
                list.data.length
                  ? "Nothing matches the filter."
                  : `No ${TITLES[kind].title.toLowerCase()} yet.`
              }
            />
          </div>
        )}
      </div>
      {editable && (
        <NewComponentDialog
          instance={instance}
          kind={kind}
          rows={list.data ?? []}
          open={creating}
          onOpenChange={setCreating}
        />
      )}
    </div>
  );
}
