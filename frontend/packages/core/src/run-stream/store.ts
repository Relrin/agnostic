// The registry of live RunStreams, shared by Chat, Sessions and (later) the Studio test pane, plus the React hooks.
import { useStore } from "zustand";
import { createStore } from "zustand/vanilla";

import type { RunState } from "./reducer";
import {
  RunStream,
  type RunStreamOptions,
  type RunStreamState,
  type RunTarget,
  type SubmitInput,
} from "./run-stream";

type Registry = { streams: Record<string, RunStream> };

export const runRegistry = createStore<Registry>(() => ({ streams: {} }));

function register(stream: RunStream): RunStream {
  runRegistry.setState((state) => ({ streams: { ...state.streams, [stream.key]: stream } }));
  return stream;
}

/** Start a run; the stream is registered under its key until `releaseRun`. */
export function startRun(target: RunTarget, input: SubmitInput, options?: RunStreamOptions): RunStream {
  const stream = register(new RunStream(target, { sessionId: input.sessionId }, options));
  void stream.submit(input);
  return stream;
}

/** The registered stream of a run, or a new idle one (to continue a paused run loaded from history). */
export function ensureRun(
  target: RunTarget,
  run: Pick<RunState, "runId" | "sessionId"> & Partial<RunState>,
): RunStream {
  const existing = findRun(run.runId);
  if (existing) return existing;
  return register(new RunStream(target, run));
}

/** Attach to a run that is (or may still be) going: after a refresh, or after an approval decision. */
export function attachRun(
  target: RunTarget,
  run: Pick<RunState, "runId" | "sessionId"> & Partial<RunState>,
  options?: RunStreamOptions & { fromStart?: boolean; key?: string },
): RunStream {
  const existing = Object.values(runRegistry.getState().streams).find(
    (stream) => stream.getState().runId === run.runId && stream.target.instance === target.instance,
  );
  if (existing) {
    void existing.resume({ fromStart: options?.fromStart ?? false });
    return existing;
  }
  const stream = register(new RunStream(target, { ...run, status: "running" }, options, options?.key));
  void stream.resume({ fromStart: options?.fromStart ?? false });
  return stream;
}

/** Resume every run this tab was streaming on `instance` before a refresh. */
export function restoreRuns(instance: string, options?: RunStreamOptions): RunStream[] {
  return RunStream.restorable(instance).map((item) =>
    attachRun(
      item.target,
      { runId: item.runId, sessionId: item.sessionId, input: item.input },
      { ...options, key: item.key },
    ),
  );
}

export function findRun(runId: string | undefined): RunStream | undefined {
  if (!runId) return undefined;
  return Object.values(runRegistry.getState().streams).find((stream) => stream.getState().runId === runId);
}

export function releaseRun(key: string): void {
  const stream = runRegistry.getState().streams[key];
  if (!stream) return;
  stream.dispose();
  runRegistry.setState((state) => {
    const rest = { ...state.streams };
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete -- the registry is keyed by run key
    delete rest[key];
    return { streams: rest };
  });
}

const EMPTY: RunStreamState | undefined = undefined;
const placeholder = createStore<RunStreamState | undefined>(() => EMPTY);

/** The live state of a stream (re-renders on every reduced event). */
export function useRunStream(stream: RunStream | undefined): RunStreamState | undefined {
  const live = useStore(stream?.store ?? placeholder);
  return stream ? live : undefined;
}

/** Streams in the registry (keys and runs), e.g. to find the live run of a session. */
export function useRunStreams(): Record<string, RunStream> {
  return useStore(runRegistry, (state) => state.streams);
}
