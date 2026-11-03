// "Run test": the draft runs with a sample input through Studio's elevated test-run endpoint. Its step events light
// the canvas up as they arrive (running, done, waiting for a person, failed); a paused step's question is answered
// right here in the run view.
import { apiUrl } from "@agnostic/api";
import { RunView, releaseRun, startRun, useRunStream, type RunStream, type RunTarget } from "@agnostic/core";
import { Button, Textarea, type WorkflowNodeStatus } from "@agnostic/ui";
import { Play, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type StepState = { name: string; status: string; children: StepState[] };

/** Step name → how it went, from the run's step tree. */
export function stepStatuses(steps: readonly StepState[] | undefined): Map<string, WorkflowNodeStatus> {
  const found = new Map<string, WorkflowNodeStatus>();
  const walk = (items: readonly StepState[]) => {
    for (const item of items) {
      const status: WorkflowNodeStatus =
        item.status === "running"
          ? "running"
          : item.status === "paused"
            ? "paused"
            : item.status === "error" || item.status === "failed"
              ? "failed"
              : item.status === "skipped"
                ? "skipped"
                : "done";
      found.set(item.name, status);
      walk(item.children);
    }
  };
  walk(steps ?? []);
  return found;
}

export function useTestRun(instance: string, componentId: string) {
  const [stream, setStream] = useState<RunStream | undefined>(undefined);
  const key = useRef<string | undefined>(undefined);
  const state = useRunStream(stream);
  useEffect(
    () => () => {
      if (key.current) releaseRun(key.current);
    },
    [],
  );
  const target: RunTarget = { instance, family: "workflows", componentId };
  return {
    stream,
    state,
    target,
    start: (message: string, version: number) => {
      if (key.current) releaseRun(key.current);
      const endpoint = apiUrl(
        `/api/v1/instances/${encodeURIComponent(instance)}/studio/components/${encodeURIComponent(componentId)}/test-runs`,
      );
      const started = startRun(
        target,
        { message, version },
        { endpoint: { submit: endpoint }, resumable: false },
      );
      key.current = started.key;
      setStream(started);
    },
    clear: () => {
      if (key.current) releaseRun(key.current);
      key.current = undefined;
      setStream(undefined);
    },
  };
}

export function RunTestPanel({
  run,
  instanceName,
  componentName,
  version,
  beforeRun,
  onClose,
}: {
  run: ReturnType<typeof useTestRun>;
  instanceName: string;
  componentName: string;
  version: number | undefined;
  beforeRun: () => Promise<boolean>;
  onClose: () => void;
}) {
  const [message, setMessage] = useState("");
  const send = async () => {
    const text = message.trim();
    if (!text || version === undefined) return;
    if (!(await beforeRun())) return;
    run.start(text, version);
  };
  return (
    <section
      aria-label="Run test"
      className="flex max-h-[45vh] min-h-0 shrink-0 flex-col gap-2 overflow-y-auto border-t border-border bg-surface p-3"
    >
      <div className="flex items-center gap-2">
        <h2 className="text-[13px] font-semibold">{`Run test · draft v${String(version ?? "")}`}</h2>
        <span className="flex-1" />
        <Button variant="icon" size="28" aria-label="Close the test run" onClick={onClose}>
          <X aria-hidden />
        </Button>
      </div>
      <div className="flex items-end gap-2">
        <Textarea
          aria-label="Sample input"
          rows={2}
          placeholder="I was charged twice, need a refund"
          value={message}
          onChange={(event) => {
            setMessage(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void send();
          }}
        />
        <Button
          variant="primary"
          size="32"
          disabled={!message.trim() || version === undefined}
          onClick={() => void send()}
        >
          <Play aria-hidden />
          Run
        </Button>
      </div>
      {run.state && (
        <RunView
          state={run.state}
          stream={run.stream}
          target={run.target}
          instanceName={instanceName}
          componentName={componentName}
          versionLabel={version !== undefined ? `draft v${String(version)}` : undefined}
        />
      )}
    </section>
  );
}
