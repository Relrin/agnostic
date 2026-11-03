// The Test pane: run the draft (its pinned version, through Studio's elevated test-run endpoint) or the current
// version, optionally both side by side, with the structured output checked against the output schema.
import { apiUrl, type RegistryEntryOut, type VersionOut } from "@agnostic/api";
import {
  RunView,
  releaseRun,
  startRun,
  useRunStream,
  type Can,
  type RunStream,
  type RunTarget,
} from "@agnostic/core";
import {
  Button,
  Callout,
  Checkbox,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  cn,
} from "@agnostic/ui";
import { SendHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { isRecord } from "./config";

type Choice = "draft" | "current";

/** Does `value` have every property the schema requires (or, without `required`, any of its properties)? */
export function checkStructured(
  value: unknown,
  schemaText: string | null | undefined,
): { valid: boolean; missing: string[] } {
  if (!isRecord(value)) return { valid: false, missing: [] };
  let schema: unknown;
  try {
    schema = schemaText ? JSON.parse(schemaText) : undefined;
  } catch {
    schema = undefined;
  }
  if (!isRecord(schema)) return { valid: true, missing: [] };
  const required = Array.isArray(schema.required)
    ? schema.required.map(String)
    : isRecord(schema.properties)
      ? Object.keys(schema.properties)
      : [];
  const missing = required.filter((key) => !(key in value));
  return { valid: missing.length === 0, missing };
}

function StructuredCard({ value, schema }: { value: unknown; schema: RegistryEntryOut | undefined }) {
  const result = checkStructured(value, schema?.code);
  return (
    <div className="overflow-hidden rounded-card border border-border bg-inset">
      <div className="flex items-center gap-2 border-b border-border-subtle px-3 py-1.5 text-[12px]">
        <span className="font-medium">Structured output{schema ? ` · ${schema.name}` : ""}</span>
        <span className="flex-1" />
        <span className={cn("font-mono text-[11.5px]", result.valid ? "text-accent" : "text-danger")}>
          {result.valid ? "valid" : `missing ${result.missing.join(", ")}`}
        </span>
      </div>
      <pre className="overflow-auto p-3 font-mono text-[12px]">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function LiveRun({
  stream,
  target,
  instanceName,
  componentName,
  versionLabel,
  schema,
}: {
  stream: RunStream;
  target: RunTarget;
  instanceName: string;
  componentName: string;
  versionLabel: string;
  schema: RegistryEntryOut | undefined;
}) {
  const state = useRunStream(stream);
  if (!state) return null;
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2" aria-live="polite">
      <RunView
        state={state}
        stream={stream}
        target={target}
        instanceName={instanceName}
        componentName={componentName}
        versionLabel={versionLabel}
      />
      {state.structured !== undefined && <StructuredCard value={state.structured} schema={schema} />}
    </div>
  );
}

export function TestPane({
  instance,
  instanceName,
  componentId,
  componentName,
  kind,
  draft,
  currentVersion,
  outputSchema,
  canTestDraft,
  beforeRun,
}: {
  instance: string;
  instanceName: string;
  componentId: string;
  componentName: string;
  kind: "agent" | "team";
  draft: VersionOut | undefined;
  currentVersion: number | null | undefined;
  outputSchema: RegistryEntryOut | undefined;
  /** `components:write` (plus run) on the instance: drafts run through delegated elevation. */
  canTestDraft: Can;
  /** Save pending edits first, so the run sees them. */
  beforeRun: () => Promise<boolean>;
}) {
  const [choice, setChoice] = useState<Choice>(draft ? "draft" : "current");
  const [compare, setCompare] = useState(false);
  const [message, setMessage] = useState("");
  const [runs, setRuns] = useState<{ main: RunStream; versus?: RunStream | undefined } | undefined>(
    undefined,
  );
  const keys = useRef<string[]>([]);
  const target: RunTarget = { instance, family: kind === "team" ? "teams" : "agents", componentId };
  const canDraft = draft !== undefined && canTestDraft.allowed === true;
  const hasCurrent = currentVersion !== null && currentVersion !== undefined;
  const runningDraft = choice === "draft" && draft !== undefined;

  useEffect(
    () => () => {
      for (const key of keys.current) releaseRun(key);
    },
    [],
  );

  const send = async () => {
    const text = message.trim();
    if (!text) return;
    if (runningDraft && !(await beforeRun())) return;
    for (const key of keys.current) releaseRun(key);
    const endpoint = apiUrl(
      `/api/v1/instances/${encodeURIComponent(instance)}/studio/components/${encodeURIComponent(componentId)}/test-runs`,
    );
    const main =
      draft && choice === "draft"
        ? startRun(
            target,
            { message: text, version: draft.version },
            { endpoint: { submit: endpoint }, resumable: false },
          )
        : startRun(target, { message: text }, { persist: false });
    const versus =
      compare && runningDraft && hasCurrent
        ? startRun(target, { message: text }, { persist: false })
        : undefined;
    keys.current = [main.key, ...(versus ? [versus.key] : [])];
    setRuns({ main, versus });
    setMessage("");
  };

  const draftLabel = draft ? `Draft v${String(draft.version)}` : "Draft";
  const currentLabel = hasCurrent ? `v${String(currentVersion)} · current` : "current";
  return (
    <section
      aria-label="Test the draft"
      className="flex min-h-0 flex-col gap-3 rounded-card border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[13.5px] font-semibold">Test</h2>
        <span className="flex-1" />
        <Select
          value={choice}
          onValueChange={(next) => {
            setChoice(next as Choice);
          }}
        >
          <SelectTrigger aria-label="Version to test" className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {draft && (
              <SelectItem value="draft" disabled={!canDraft}>
                {draftLabel}
              </SelectItem>
            )}
            {hasCurrent && <SelectItem value="current">{currentLabel}</SelectItem>}
          </SelectContent>
        </Select>
      </div>
      {draft && hasCurrent && runningDraft && (
        <Checkbox
          checked={compare}
          onCheckedChange={(checked) => {
            setCompare(checked === true);
          }}
          label={`Compare with v${String(currentVersion)}`}
        />
      )}
      {draft && canTestDraft.allowed === false && (
        <Callout tone="info">
          AgentOS runs drafts only for their owner or an admin. Studio runs them for people holding
          components:write; you can test the current version.
        </Callout>
      )}
      {runs ? (
        <div className={cn("flex min-h-0 flex-1 gap-3 overflow-auto", runs.versus ? "flex-row" : "flex-col")}>
          <LiveRun
            stream={runs.main}
            target={target}
            instanceName={instanceName}
            componentName={componentName}
            versionLabel={runningDraft ? draftLabel : currentLabel}
            schema={outputSchema}
          />
          {runs.versus && (
            <LiveRun
              stream={runs.versus}
              target={target}
              instanceName={instanceName}
              componentName={componentName}
              versionLabel={currentLabel}
              schema={outputSchema}
            />
          )}
        </div>
      ) : (
        <p className="text-[12.5px] text-fg-muted">
          {hasCurrent || draft
            ? `Send a message to ${runningDraft ? draftLabel.toLowerCase() : currentLabel}.`
            : "Save a draft to test it."}
        </p>
      )}
      <form
        className="flex items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <Textarea
          aria-label="Message"
          rows={2}
          className="flex-1"
          placeholder={`Message ${runningDraft ? draftLabel.toLowerCase() : currentLabel}…`}
          value={message}
          onChange={(event) => {
            setMessage(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <Button
          type="submit"
          variant="primary"
          size="32"
          aria-label="Send"
          disabled={!message.trim() || (!hasCurrent && !canDraft)}
        >
          <SendHorizontal aria-hidden />
        </Button>
      </form>
    </section>
  );
}
