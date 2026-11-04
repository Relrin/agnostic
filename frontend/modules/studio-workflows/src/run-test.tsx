// The Playground: the draft runs with a test message through Studio's elevated test-run endpoint. Its step events
// light the canvas up as they arrive (running, done with its time, waiting for a person, failed) and each step's
// output can be inspected on its node or in the inspector; a paused step's question is answered right here.
import { apiUrl } from "@agnostic/api";
import {
  RunView,
  releaseRun,
  startRun,
  useRunStream,
  type RunStream,
  type RunTarget,
  type StepNode,
} from "@agnostic/core";
import { Button, Textarea, type WorkflowNodeStatus } from "@agnostic/ui";
import { ArrowUp, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/** How a step went in the test run: what the canvas badges and the output views show. */
export type StepResult = {
  status: WorkflowNodeStatus;
  content: string;
  ms?: number | undefined;
  error?: string | undefined;
  tools: string[];
};

function statusOf(status: string): WorkflowNodeStatus {
  if (status === "running" || status === "pending") return "running";
  if (status === "paused") return "paused";
  if (status === "error" || status === "failed") return "failed";
  if (status === "skipped" || status === "cancelled") return "skipped";
  return "done";
}

export function seconds(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${String(Math.round(ms))} ms`;
}

/** Step name → how it went, from the run's step tree. */
export function stepResults(steps: readonly StepNode[] | undefined): Map<string, StepResult> {
  const found = new Map<string, StepResult>();
  const walk = (items: readonly StepNode[]) => {
    for (const item of items) {
      const ms =
        item.startedAt !== undefined && item.endedAt !== undefined
          ? item.endedAt - item.startedAt
          : undefined;
      found.set(item.name, {
        status: statusOf(item.status),
        content: item.content,
        ms,
        error: item.error,
        tools: item.tools.map((tool) => tool.name),
      });
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

export function PlaygroundPanel({
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
    setMessage("");
  };
  return (
    <aside
      aria-label="Playground"
      className="flex min-h-0 w-[min(380px,42vw)] shrink-0 flex-col border-l border-border bg-rail"
    >
      <div className="flex items-center gap-2 border-b border-border-subtle py-2.5 pr-2.5 pl-4">
        <h2 className="text-[14px] font-semibold">Playground</h2>
        <span className="flex-1" />
        <span className="text-[12px] text-fg-muted">{`draft v${String(version ?? "")} · test run`}</span>
        <Button variant="icon" size="28" aria-label="Close the playground" onClick={onClose}>
          <X aria-hidden />
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-3.5">
        {run.state ? (
          <RunView
            state={run.state}
            stream={run.stream}
            target={run.target}
            instanceName={instanceName}
            componentName={componentName}
            versionLabel={version !== undefined ? `draft v${String(version)}` : undefined}
          />
        ) : (
          <p className="text-[12.5px] text-fg-muted">
            Send a message to run the draft. Each step lights up on the canvas as it runs, and its output
            shows on the node.
          </p>
        )}
      </div>
      <form
        aria-label="Message the workflow"
        className="m-3 flex items-end gap-2 rounded-radio border border-border-strong bg-surface py-1.5 pr-1.5 pl-3"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <Textarea
          aria-label="Test message"
          rows={1}
          placeholder="Send a test message…"
          className="min-h-8 flex-1 resize-none border-0 bg-transparent px-0 py-1.5 font-sans text-[13px] shadow-none focus-visible:ring-0"
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
          aria-label="Run"
          disabled={!message.trim() || version === undefined}
        >
          <ArrowUp aria-hidden />
        </Button>
      </form>
    </aside>
  );
}
