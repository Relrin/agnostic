// RunStream AgentOS run over SSE through the gateway. Submits with `background=true, stream=true` (the run
// survives a dropped connection), reduces events into a RunState, and reconnects with `/resume` +
// `last_event_index` when the stream ends before the run settles: a browser refresh, a gateway or API replica
// restart (unless the stream is not `resumable`). Cancel and continue (agents `tools`, teams `requirements`, workflows `step_requirements`) go through the
// same object.
import { describeError, gatewayFetch, gatewayUrl, isProblem, writeHeaders } from "@agnostic/api";
import { fetchEventSource, type EventSourceMessage } from "@microsoft/fetch-event-source";
import { createStore, type StoreApi } from "zustand/vanilla";

import { META_EVENTS, parseEvent } from "./events";
import { initialRunState, isSettled, reduceRun, type ComponentKind, type RunState } from "./reducer";

export type RunFamily = "agents" | "teams" | "workflows";

export const FAMILY_KIND: Record<RunFamily, ComponentKind> = {
  agents: "agent",
  teams: "team",
  workflows: "workflow",
};

export type RunTarget = { instance: string; family: RunFamily; componentId: string };

export type SubmitInput = {
  message: string;
  sessionId?: string | undefined;
  version?: number | undefined;
  files?: readonly File[] | undefined;
};

export type RunStreamOptions = {
  /** Injected in tests (recorded SSE fixtures). */
  fetch?: typeof fetch;
  /** Backoff between /resume attempts, in ms. */
  retryDelays?: readonly number[];
  /** Persist active runs in sessionStorage so a refresh can resume them (default: `resumable`). */
  persist?: boolean;
  /**
   * Where to submit instead of the gateway's `{family}/{id}/runs` (a full URL, e.g. a control-plane endpoint that
   * runs a draft), as a JSON body. Continue, resume and cancel still go through the gateway with the run id it
   * returns.
   */
  endpoint?: { submit: string } | undefined;
  /**
   * Reconnect with `/resume` when the stream drops before the run settles (default true). When false, a drop ends
   * the stream in an error state that says to run it again.
   */
  resumable?: boolean;
};

export type StreamPhase = "idle" | "connecting" | "streaming" | "reconnecting" | "closed";

export type RunStreamState = RunState & { phase: StreamPhase; attempts: number };

const DEFAULT_DELAYS = [500, 1000, 2000, 4000, 8000, 15000];
const DROPPED = "The connection dropped before the run finished. Run it again to retry.";
const STORAGE_KEY = "agnostic.active-runs";

class FatalStreamError extends Error {}

type Persisted = {
  key: string;
  target: RunTarget;
  runId: string;
  sessionId?: string | undefined;
  input?: string | undefined;
};

function readPersisted(): Persisted[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Persisted[]) : [];
  } catch {
    return [];
  }
}

function writePersisted(items: Persisted[]): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {
    // Private mode or storage disabled: refresh-resume is a nicety.
  }
}

let counter = 0;
function newKey(): string {
  counter += 1;
  return `run-${Date.now().toString(36)}-${counter.toString(36)}`;
}

function form(fields: Record<string, string | undefined>): URLSearchParams {
  const body = new URLSearchParams();
  for (const [name, value] of Object.entries(fields)) if (value !== undefined) body.set(name, value);
  return body;
}

export class RunStream {
  readonly key: string;
  readonly target: RunTarget;
  readonly store: StoreApi<RunStreamState>;
  private controller: AbortController | undefined;
  private readonly fetchImpl: typeof fetch | undefined;
  private readonly delays: readonly number[];
  private readonly persist: boolean;
  private readonly resumable: boolean;
  private readonly submitUrl: string | undefined;
  private openError: string | undefined;
  private disposed = false;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    target: RunTarget,
    initial: Partial<RunState> = {},
    options: RunStreamOptions = {},
    key = newKey(),
  ) {
    this.key = key;
    this.target = target;
    this.fetchImpl = options.fetch;
    this.delays = options.retryDelays ?? DEFAULT_DELAYS;
    this.resumable = options.resumable ?? true;
    this.persist = options.persist ?? this.resumable;
    this.submitUrl = options.endpoint?.submit;
    this.store = createStore<RunStreamState>(() => ({
      ...initialRunState({ kind: FAMILY_KIND[target.family], componentId: target.componentId, ...initial }),
      phase: "idle",
      attempts: 0,
    }));
  }

  getState(): RunStreamState {
    return this.store.getState();
  }

  private set(update: Partial<RunStreamState>): void {
    this.store.setState(update);
  }

  private base(): string {
    return `${this.target.family}/${encodeURIComponent(this.target.componentId)}/runs`;
  }

  private gateway(path: string): string {
    return gatewayUrl(this.target.instance, path);
  }

  /**
   * Start a run: multipart for agents and teams (files allowed), a form for workflows, and JSON
   * (`message`, `version`, `session_id`) to a custom `endpoint`, which takes no files.
   */
  async submit(input: SubmitInput): Promise<void> {
    if (this.submitUrl && input.files?.length) {
      throw new Error("Files can't be attached to a run submitted to a custom endpoint.");
    }
    this.set({
      input: input.message,
      status: "pending",
      sessionId: input.sessionId ?? this.getState().sessionId,
    });
    let body: BodyInit;
    const common = {
      message: input.message,
      stream: "true",
      background: "true",
      session_id: input.sessionId,
      version: input.version === undefined ? undefined : String(input.version),
    };
    if (this.submitUrl) {
      const json = { message: input.message, version: input.version, session_id: input.sessionId };
      await this.open(this.submitUrl, JSON.stringify(json), {
        "Content-Type": "application/json",
        "Idempotency-Key": this.key,
      });
      return;
    }
    if (this.target.family === "workflows") {
      body = form(common);
    } else {
      const multipart = new FormData();
      for (const [name, value] of Object.entries(common)) if (value !== undefined) multipart.set(name, value);
      for (const file of input.files ?? []) multipart.append("files", file, file.name);
      body = multipart;
    }
    await this.open(this.gateway(this.base()), body, { "Idempotency-Key": this.key });
  }

  /**
   * Reconnect to a run that is still going (or replay one that finished). `fromStart` replays every buffered event
   * into a fresh state: used after an approval decision, when the run continued in the background.
   */
  async resume({ fromStart = false }: { fromStart?: boolean } = {}): Promise<void> {
    const state = this.getState();
    if (!state.runId) {
      this.set({
        status: "error",
        error: { message: "The connection dropped before the run started." },
        phase: "closed",
      });
      return;
    }
    if (fromStart) {
      this.set({
        ...initialRunState({
          kind: state.kind,
          runId: state.runId,
          sessionId: state.sessionId,
          componentId: state.componentId,
          componentName: state.componentName,
          input: state.input,
        }),
        status: "running",
      });
    }
    const last = this.getState().lastEventIndex;
    await this.open(
      this.gateway(`${this.base()}/${encodeURIComponent(state.runId)}/resume`),
      form({ last_event_index: last >= 0 ? String(last) : undefined, session_id: state.sessionId }),
    );
  }

  async cancel(): Promise<void> {
    const state = this.getState();
    if (!state.runId) {
      this.dispose();
      return;
    }
    const query = state.sessionId ? `?session_id=${encodeURIComponent(state.sessionId)}` : "";
    await gatewayFetch(
      this.target.instance,
      `${this.base()}/${encodeURIComponent(state.runId)}/cancel${query}`,
      {
        method: "POST",
      },
    );
  }

  /** Continue a paused run with resolved requirements (fields are JSON strings, as AgentOS expects). */
  async continueRun(fields: {
    tools?: string;
    requirements?: string;
    step_requirements?: string;
  }): Promise<void> {
    const state = this.getState();
    if (!state.runId) return;
    this.set({ status: "running", pause: undefined, lastEventIndex: -1 });
    await this.open(
      this.gateway(`${this.base()}/${encodeURIComponent(state.runId)}/continue`),
      form({ ...fields, session_id: state.sessionId, stream: "true", background: "true" }),
    );
  }

  dispose(): void {
    this.disposed = true;
    clearTimeout(this.retryTimer);
    this.controller?.abort();
    this.set({ phase: "closed" });
    this.forget();
  }

  private isDisposed(): boolean {
    return this.disposed;
  }

  // ------------------------------------------------------------ transport

  private async open(url: string, body: BodyInit, extra: Record<string, string> = {}): Promise<void> {
    if (this.disposed) return;
    clearTimeout(this.retryTimer);
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    this.set({ phase: this.getState().attempts > 0 ? "reconnecting" : "connecting" });
    const headers = writeHeaders("POST", { Accept: "text/event-stream", ...extra });
    let fatal = false;
    this.openError = undefined;
    try {
      await fetchEventSource(url, {
        method: "POST",
        headers: Object.fromEntries(headers.entries()),
        body,
        credentials: "same-origin",
        signal: controller.signal,
        openWhenHidden: true,
        ...(this.fetchImpl ? { fetch: this.fetchImpl } : {}),
        onopen: async (response) => {
          const type = response.headers.get("content-type") ?? "";
          if (response.ok && type.includes("text/event-stream")) {
            this.set({ phase: "streaming" });
            return;
          }
          await this.openFailed(response);
        },
        onmessage: (message) => {
          this.handle(message);
        },
        onerror: (error: unknown) => {
          // Never let fetch-event-source retry on its own: reconnecting means /resume, with our index.
          throw error;
        },
      });
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof FatalStreamError) fatal = true;
    }
    if (controller.signal.aborted || this.isDisposed()) return;
    const state = this.getState();
    if (fatal || isSettled(state)) {
      this.set({ phase: "closed", attempts: 0 });
      this.save();
      return;
    }
    if (!this.resumable) {
      this.dropped();
      return;
    }
    this.scheduleResume();
  }

  /** A non-resumable stream ended early: say why (when the gateway did) and that running it again is the retry. */
  private dropped(): void {
    const detail = this.openError;
    this.set({
      phase: "closed",
      attempts: 0,
      status: "error",
      error: { message: detail ? `${detail}. Run it again to retry.` : DROPPED, type: "connection" },
    });
  }

  private async openFailed(response: Response): Promise<never> {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    if (response.ok && typeof body === "object" && body !== null && "run_id" in body) {
      // 202 from a non-streaming continuation: the run goes on in the background; replay it.
      const accepted = body as { run_id?: string; session_id?: string };
      this.set({
        runId: accepted.run_id ?? this.getState().runId,
        sessionId: accepted.session_id ?? this.getState().sessionId,
      });
      throw new Error("accepted without a stream");
    }
    const detail = isProblem(body)
      ? describeError(body).reason
      : typeof body === "object" && body !== null && "detail" in body
        ? String(body.detail)
        : `HTTP ${String(response.status)}`;
    // 404/410 on /resume: the run is gone from every buffer; anything else 4xx is the request's fault.
    if (response.status >= 400 && response.status < 500) {
      this.set({ status: "error", error: { message: detail, type: `HTTP ${String(response.status)}` } });
      throw new FatalStreamError(detail);
    }
    this.openError = detail;
    throw new Error(detail);
  }

  private handle(message: EventSourceMessage): void {
    if (META_EVENTS.has(message.event)) {
      if (message.event === "error") {
        let detail = "This run is no longer streaming.";
        try {
          const parsed = JSON.parse(message.data) as { error?: string; detail?: string };
          detail = parsed.error ?? parsed.detail ?? detail;
        } catch {
          // keep the default
        }
        const state = this.getState();
        if (!isSettled(state)) this.set({ status: "error", error: { message: detail, type: "resume" } });
      }
      return;
    }
    const event = parseEvent(message.event, message.data);
    if (!event) return;
    const before = this.getState();
    const next = reduceRun(before, event);
    if (next !== before) {
      this.store.setState({ ...next, phase: "streaming", attempts: 0 });
      if (!before.runId && next.runId) this.save();
    }
  }

  private scheduleResume(): void {
    const attempts = this.getState().attempts;
    const delay = this.delays[attempts];
    if (delay === undefined) {
      this.set({
        phase: "closed",
        status: "error",
        error: { message: "Lost the connection to the run. Refresh to try again.", type: "connection" },
      });
      return;
    }
    this.set({ phase: "reconnecting", attempts: attempts + 1 });
    this.retryTimer = setTimeout(() => {
      void this.resume();
    }, delay);
  }

  // ------------------------------------------------------------ refresh survival

  private save(): void {
    if (!this.persist) return;
    const state = this.getState();
    const others = readPersisted().filter((item) => item.key !== this.key);
    if (state.runId && !isSettled(state) && !this.disposed) {
      others.push({
        key: this.key,
        target: this.target,
        runId: state.runId,
        sessionId: state.sessionId,
        input: state.input,
      });
    }
    writePersisted(others);
  }

  private forget(): void {
    if (this.persist) writePersisted(readPersisted().filter((item) => item.key !== this.key));
  }

  /** Runs that were streaming in this tab before a refresh, for `instance`. */
  static restorable(instance: string): Persisted[] {
    return readPersisted().filter((item) => item.target.instance === instance);
  }
}
