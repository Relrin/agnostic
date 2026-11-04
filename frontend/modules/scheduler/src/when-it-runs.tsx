// "When it runs": the five cron fields (read-only in the detail, editable in the form), the timezone, the cron as a
// sentence, the next 5 runs in local time and UTC, and daylight-saving notes.
import { describeError } from "@agnostic/api";
import { timezones } from "@agnostic/core";
import {
  CRON_FIELDS,
  Callout,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  cn,
} from "@agnostic/ui";
import { useMemo } from "react";

import { invalidFields, wallTime, type Preview } from "./schedules-api";

/** The cron fields as a read-only grid (labelled like the editable `CronFields`). */
export function CronReadout({ cron }: { cron: string }) {
  const parts = cron.trim().split(/\s+/);
  return (
    <dl aria-label="Cron fields" className="grid grid-cols-5 gap-2">
      {CRON_FIELDS.map((name, index) => (
        <div key={name} className="flex flex-col gap-1">
          <dt className="text-[11.5px] text-fg-muted">{name}</dt>
          <dd className="flex h-[34px] items-center justify-center rounded-control border border-border-input bg-inset font-mono text-[12.5px]">
            {parts[index] ?? "*"}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function TimezoneSelect({
  id,
  value,
  onChange,
  invalid = false,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  invalid?: boolean;
}) {
  const zones = useMemo(() => timezones(value), [value]);
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        id={id}
        aria-label={id ? undefined : "Timezone"}
        aria-invalid={invalid || undefined}
        className="font-mono"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {zones.map((zone) => (
          <SelectItem key={zone} value={zone}>
            {zone}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** The summary box: the sentence, "Next 5 runs" (local left, UTC right; the first highlighted) and DST notes. */
export function RunPreview({ preview, cron }: { preview: Preview; cron: string }) {
  if (!cron.trim())
    return (
      <p className="rounded-tile border border-border bg-surface px-3.5 py-3 text-[13px] text-fg-secondary">
        No cron expression: this schedule runs only when triggered.
      </p>
    );
  if (preview.isError) {
    const fields = invalidFields(preview.error);
    return (
      <Callout tone="danger" title="This cron expression doesn't parse">
        {describeError(preview.error).reason}
        {fields.length > 0 && ` Check ${fields.join(", ")}.`}
      </Callout>
    );
  }
  const data = preview.data;
  return (
    <div className="flex flex-col gap-3">
      <div
        aria-label="Next runs"
        role="group"
        className="flex flex-col gap-2.5 rounded-tile border border-border bg-surface px-3.5 py-3"
      >
        {data ? (
          <>
            <p className="text-[14px] font-medium">{data.human}</p>
            <div className="flex flex-col gap-1">
              <span className="text-[11.5px] text-fg-muted">Next {data.runs.length} runs</span>
              <ol className="flex flex-col gap-0.5 font-mono text-[12px]">
                {data.runs.map((run, index) => {
                  const local = wallTime(run.local);
                  const utc = wallTime(run.utc);
                  return (
                    <li
                      key={run.utc}
                      aria-current={index === 0 ? "true" : undefined}
                      className={cn(
                        "flex items-baseline justify-between gap-3 rounded-badge px-1.5 py-0.5",
                        index === 0 ? "bg-accent/10 text-accent" : "text-fg-secondary",
                      )}
                    >
                      <span>
                        {local.date} · {local.time}
                      </span>
                      <span className={index === 0 ? undefined : "text-fg-muted"}>
                        {utc.date === local.date ? "" : `${utc.date.split(" ").slice(0, 3).join(" ")} · `}
                        {utc.time} UTC
                      </span>
                    </li>
                  );
                })}
              </ol>
            </div>
          </>
        ) : (
          <>
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-16 w-full" />
          </>
        )}
      </div>
      {data?.notes.map((note) => (
        <Callout key={note} tone="warning">
          {note}
        </Callout>
      ))}
    </div>
  );
}
