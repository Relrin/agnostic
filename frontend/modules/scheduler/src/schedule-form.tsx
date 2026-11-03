// New / Edit schedule: name, target (an agent, team or workflow run, or a custom endpoint for Instance admins),
// "When it runs" with a live preview, and the request (payload, timeout, retries, retry delay).
import { describeError, type Method, type ScheduleIn, type SchedulePatch } from "@agnostic/api";
import { useComponents } from "@agnostic/core";
import {
  Button,
  Callout,
  CronFields,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useState, type ReactNode } from "react";

import {
  FAMILY,
  METHODS,
  NAME_PATTERN,
  fieldErrors,
  invalidFields,
  localTimezone,
  useEndpointCheck,
  usePreview,
  useScheduleActions,
  type Schedule,
  type TargetKind,
} from "./schedules-api";
import { RunPreview, TimezoneSelect } from "./when-it-runs";

type Mode = TargetKind | "custom";

const DEFAULT_PAYLOAD = JSON.stringify({ message: "", stream: false }, null, 2);
const KIND_LABEL: Record<TargetKind, string> = { agent: "Agent", team: "Team", workflow: "Workflow" };

function parsePayload(text: string): { value?: Record<string, unknown>; error?: string } {
  if (!text.trim()) return { value: {} };
  try {
    const parsed = JSON.parse(text) as unknown;
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
      return { error: "The payload must be a JSON object." };
    return { value: parsed as Record<string, unknown> };
  } catch (problem) {
    return { error: problem instanceof Error ? problem.message : "Not valid JSON." };
  }
}

function wholeNumber(text: string, min: number, max: number): number | undefined {
  const value = Number(text);
  return Number.isInteger(value) && value >= min && value <= max ? value : undefined;
}

function FormSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-3 border-t border-border-subtle pt-4">
      <legend className="float-left mb-1 text-[13.5px] font-semibold">{title}</legend>
      {children}
    </fieldset>
  );
}

export function ScheduleFormDialog({
  instance,
  schedule,
  canCustom,
  onClose,
  onSaved,
}: {
  instance: string;
  /** The schedule being edited; a new one when undefined. */
  schedule?: Schedule | undefined;
  canCustom: boolean;
  onClose: () => void;
  onSaved: (schedule: Schedule) => void;
}) {
  const actions = useScheduleActions(instance);
  const initialMode: Mode = schedule?.target_kind ?? "agent";
  const [name, setName] = useState(schedule?.name ?? "");
  const [description, setDescription] = useState(schedule?.description ?? "");
  const [mode, setMode] = useState<Mode>(initialMode);
  const [componentId, setComponentId] = useState(
    schedule && schedule.target_kind !== "custom" ? (schedule.target_id ?? "") : "",
  );
  const [method, setMethod] = useState<Method>(
    schedule?.target_kind === "custom" ? (schedule.method.toUpperCase() as Method) : "POST",
  );
  const [path, setPath] = useState(schedule?.target_kind === "custom" ? schedule.endpoint : "");
  const [cron, setCron] = useState(schedule ? (schedule.cron_expr ?? "") : "0 9 * * 1-5");
  const [timezone, setTimezone] = useState(schedule?.timezone ?? localTimezone());
  const [payload, setPayload] = useState(
    schedule ? JSON.stringify(schedule.payload ?? {}, null, 2) : DEFAULT_PAYLOAD,
  );
  const [timeout, setTimeoutText] = useState(String(schedule?.timeout_seconds ?? 3600));
  const [retries, setRetries] = useState(String(schedule?.max_retries ?? 0));
  const [delay, setDelay] = useState(String(schedule?.retry_delay_seconds ?? 60));

  const custom = mode === "custom";
  const family = custom ? "agents" : FAMILY[mode];
  const components = useComponents(custom ? undefined : instance, family);
  const ids = (components.data ?? []).map((item) => item.id);
  const original = schedule?.target_kind === mode ? (schedule.target_id ?? "") : "";
  const options = original && !ids.includes(original) ? [original, ...ids] : ids;
  const target = componentId && options.includes(componentId) ? componentId : (options[0] ?? "");
  const endpoint = custom ? path.trim() : target ? `/${family}/${target}/runs` : "";
  const sentMethod: Method = custom ? method : "POST";
  const check = useEndpointCheck(instance, method, path, custom);
  const preview = usePreview(instance, cron, timezone);
  const save = schedule ? actions.update : actions.create;

  const parsed = parsePayload(payload);
  const payloadValue = parsed.value;
  const nameError =
    name && !NAME_PATTERN.test(name)
      ? "Start with a letter or digit; then letters, digits, spaces, dots, underscores or dashes."
      : undefined;
  const timeoutValue = wholeNumber(timeout, 1, 86_400);
  const retriesValue = wholeNumber(retries, 0, 10);
  const delayValue = wholeNumber(delay, 1, 3600);
  const server = save.isError ? fieldErrors(save.error) : {};
  const badFields = [...invalidFields(preview.error), ...(save.isError ? invalidFields(save.error) : [])];
  const ready =
    name.trim() !== "" &&
    !nameError &&
    endpoint.startsWith("/") &&
    payloadValue !== undefined &&
    timeoutValue !== undefined &&
    retriesValue !== undefined &&
    delayValue !== undefined;

  const submit = () => {
    if (!ready) return;
    const values: ScheduleIn = {
      name: name.trim(),
      description: description.trim() || null,
      cron_expr: cron.trim(),
      timezone,
      method: sentMethod,
      endpoint,
      payload: payloadValue,
      timeout_seconds: timeoutValue,
      max_retries: retriesValue,
      retry_delay_seconds: delayValue,
    };
    const done = (saved: Schedule) => {
      toast.success(schedule ? `Saved ${saved.name}` : `Created ${saved.name}`);
      onSaved(saved);
    };
    if (!schedule) {
      actions.create.mutate(values, { onSuccess: done });
      return;
    }
    const body: SchedulePatch = {};
    if (values.name !== schedule.name) body.name = values.name;
    if ((values.description ?? null) !== (schedule.description ?? null))
      body.description = values.description ?? "";
    if (values.cron_expr !== (schedule.cron_expr ?? "")) body.cron_expr = values.cron_expr ?? "";
    if (values.timezone !== schedule.timezone) body.timezone = values.timezone ?? "UTC";
    if (values.method !== schedule.method) body.method = values.method ?? "POST";
    if (values.endpoint !== schedule.endpoint) body.endpoint = values.endpoint;
    if (JSON.stringify(values.payload) !== JSON.stringify(schedule.payload ?? {}))
      body.payload = values.payload ?? null;
    if (values.timeout_seconds !== schedule.timeout_seconds)
      body.timeout_seconds = values.timeout_seconds ?? null;
    if (values.max_retries !== schedule.max_retries) body.max_retries = values.max_retries ?? null;
    if (values.retry_delay_seconds !== schedule.retry_delay_seconds)
      body.retry_delay_seconds = values.retry_delay_seconds ?? null;
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    actions.update.mutate({ id: schedule.id, body }, { onSuccess: done });
  };

  const modes: { value: Mode; label: string }[] = [
    { value: "agent", label: "Agent" },
    { value: "team", label: "Team" },
    { value: "workflow", label: "Workflow" },
    ...(canCustom || initialMode === "custom"
      ? [{ value: "custom" as const, label: "Custom endpoint" }]
      : []),
  ];

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{schedule ? `Edit ${schedule.name}` : "New schedule"}</DialogTitle>
          <DialogDescription>
            Each run is a background run on this instance, in the schedule&apos;s own timezone.{" "}
            <code className="font-mono">{schedule ? "PATCH /schedules/{id}" : "POST /schedules"}</code> ·
            needs <code className="font-mono">schedules:write</code>
          </DialogDescription>
        </DialogHeader>
        <form
          id="schedule-form"
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
            <Field label="Name" error={nameError ?? server.name}>
              {({ id, describedBy, invalid }) => (
                <Input
                  id={id}
                  mono
                  required
                  maxLength={255}
                  placeholder="daily-brief"
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                  value={name}
                  onChange={(event) => {
                    setName(event.target.value);
                  }}
                />
              )}
            </Field>
            <Field label="Description" error={server.description}>
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  maxLength={2000}
                  placeholder="What it does, for whoever reads this next"
                  aria-describedby={describedBy}
                  value={description}
                  onChange={(event) => {
                    setDescription(event.target.value);
                  }}
                />
              )}
            </Field>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-medium text-fg-secondary">Target</span>
            <SegmentedControl label="Target" value={mode} onValueChange={setMode} options={modes} />
            {custom ? (
              <div className="grid grid-cols-[120px_1fr] gap-2">
                <Select
                  value={method}
                  onValueChange={(value) => {
                    setMethod(value as Method);
                  }}
                >
                  <SelectTrigger aria-label="Method" className="font-mono">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {METHODS.map((item) => (
                      <SelectItem key={item} value={item}>
                        {item}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  aria-label="Path"
                  mono
                  placeholder="/agents/billing-agent/runs"
                  aria-invalid={Boolean(server.endpoint) || undefined}
                  value={path}
                  onChange={(event) => {
                    setPath(event.target.value);
                  }}
                />
              </div>
            ) : (
              <Field label={KIND_LABEL[mode]}>
                {({ id }) => (
                  <Select value={target} onValueChange={setComponentId}>
                    <SelectTrigger id={id} className="font-mono">
                      <SelectValue
                        placeholder={components.isPending ? "Loading…" : `No ${family} on this instance`}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {options.map((item) => (
                        <SelectItem key={item} value={item}>
                          {item}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </Field>
            )}
            <p className="font-mono text-[12px] text-fg-muted">
              <span className="text-accent">{sentMethod}</span>{" "}
              <span aria-label="Endpoint">{endpoint || "—"}</span>
            </p>
            {server.endpoint && <p className="text-[12.5px] text-danger">{server.endpoint}</p>}
            {custom && (
              <p className="text-[12px] text-fg-muted">
                Custom endpoints need Instance admin, to create and to trigger.
              </p>
            )}
            {custom && check.data?.documented === false && (
              <Callout tone="warning">This path isn&apos;t in the instance&apos;s OpenAPI document.</Callout>
            )}
            {custom && check.data && check.data.target_kind !== "custom" && (
              <p className="text-[12px] text-fg-muted">
                This is a run of {check.data.target_kind} {check.data.target_id}.
              </p>
            )}
          </div>

          <FormSection title="When it runs">
            <CronFields value={cron || "* * * * *"} onChange={setCron} invalid={badFields} />
            <Field label="Timezone">
              {({ id }) => (
                <TimezoneSelect
                  id={id}
                  value={timezone}
                  onChange={setTimezone}
                  invalid={badFields.includes("timezone")}
                />
              )}
            </Field>
            <RunPreview preview={preview} cron={cron} />
          </FormSection>

          <FormSection title="Request">
            <Field label="payload" error={parsed.error ?? server.payload}>
              {({ id, describedBy, invalid }) => (
                <Textarea
                  id={id}
                  rows={5}
                  spellCheck={false}
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                  value={payload}
                  onChange={(event) => {
                    setPayload(event.target.value);
                  }}
                />
              )}
            </Field>
            <div className="grid grid-cols-3 gap-3">
              <Field
                label="timeout_seconds"
                error={timeoutValue === undefined ? "1 to 86400." : server.timeout_seconds}
              >
                {({ id, describedBy, invalid }) => (
                  <Input
                    id={id}
                    mono
                    type="number"
                    min={1}
                    max={86_400}
                    aria-describedby={describedBy}
                    aria-invalid={invalid || undefined}
                    value={timeout}
                    onChange={(event) => {
                      setTimeoutText(event.target.value);
                    }}
                  />
                )}
              </Field>
              <Field label="max_retries" error={retriesValue === undefined ? "0 to 10." : server.max_retries}>
                {({ id, describedBy, invalid }) => (
                  <Input
                    id={id}
                    mono
                    type="number"
                    min={0}
                    max={10}
                    aria-describedby={describedBy}
                    aria-invalid={invalid || undefined}
                    value={retries}
                    onChange={(event) => {
                      setRetries(event.target.value);
                    }}
                  />
                )}
              </Field>
              <Field
                label="retry_delay_seconds"
                error={delayValue === undefined ? "1 to 3600." : server.retry_delay_seconds}
              >
                {({ id, describedBy, invalid }) => (
                  <Input
                    id={id}
                    mono
                    type="number"
                    min={1}
                    max={3600}
                    aria-describedby={describedBy}
                    aria-invalid={invalid || undefined}
                    value={delay}
                    onChange={(event) => {
                      setDelay(event.target.value);
                    }}
                  />
                )}
              </Field>
            </div>
          </FormSection>

          {save.isError && <Callout tone="danger">{describeError(save.error).reason}</Callout>}
        </form>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="32">
              Cancel
            </Button>
          </DialogClose>
          <Button
            type="submit"
            form="schedule-form"
            variant="primary"
            size="32"
            disabled={!ready || save.isPending}
          >
            {save.isPending ? "Saving…" : schedule ? "Save changes" : "Create schedule"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
