// Realtime `/api/v1/events` SSE connection per browser, held by a leader tab. Tabs elect the leader with
// the Web Locks API (the lock is released when the tab closes or crashes, so another tab takes over at once) and
// share events over a BroadcastChannel. Browsers without Web Locks connect from every tab.
import { apiUrl } from "@agnostic/api";
import { fetchEventSource } from "@microsoft/fetch-event-source";

export type RealtimeMessage = {
  id: string | undefined;
  type: string;
  data: Record<string, unknown>;
};

export type RealtimeListener = (message: RealtimeMessage) => void;

const CHANNEL = "agnostic-realtime";
const LOCK = "agnostic-realtime-leader";
const RETRY_MS = [1000, 2000, 5000, 10000, 30000];

type Locks = { request: (name: string, callback: () => Promise<void>) => Promise<void> };

function locks(): Locks | undefined {
  const candidate = (globalThis.navigator as { locks?: Locks } | undefined)?.locks;
  return candidate && typeof candidate.request === "function" ? candidate : undefined;
}

export class RealtimeClient {
  private readonly listeners = new Set<RealtimeListener>();
  private channel: BroadcastChannel | undefined;
  private controller: AbortController | undefined;
  private release: (() => void) | undefined;
  private lastEventId: string | undefined;
  private stopped = true;
  /** Whether this tab holds the connection (for the tests and the dev tools). */
  leader = false;

  constructor(private readonly options: { fetch?: typeof fetch } = {}) {}

  subscribe(listener: RealtimeListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    if (typeof BroadcastChannel !== "undefined") {
      this.channel = new BroadcastChannel(CHANNEL);
      this.channel.onmessage = (event: MessageEvent<RealtimeMessage>) => {
        if (!this.leader) this.emit(event.data);
      };
    }
    const lockManager = locks();
    if (!lockManager) {
      void this.lead();
      return;
    }
    void lockManager.request(LOCK, () => {
      if (this.stopped) return Promise.resolve();
      return new Promise<void>((resolve) => {
        this.release = resolve;
        void this.lead();
      });
    });
  }

  stop(): void {
    this.stopped = true;
    this.leader = false;
    this.controller?.abort();
    this.release?.();
    this.release = undefined;
    this.channel?.close();
    this.channel = undefined;
  }

  private isStopped(): boolean {
    return this.stopped;
  }

  private emit(message: RealtimeMessage): void {
    for (const listener of this.listeners) listener(message);
  }

  private async lead(): Promise<void> {
    this.leader = true;
    let attempt = 0;
    while (!this.stopped) {
      const controller = new AbortController();
      this.controller = controller;
      const opened = { value: false };
      try {
        await fetchEventSource(apiUrl("/api/v1/events"), {
          headers: this.lastEventId ? { "Last-Event-ID": this.lastEventId } : {},
          credentials: "same-origin",
          signal: controller.signal,
          openWhenHidden: true,
          ...(this.options.fetch ? { fetch: this.options.fetch } : {}),
          onopen: (response) => {
            if (!response.ok) throw new Error(`events: HTTP ${String(response.status)}`);
            opened.value = true;
            attempt = 0;
            return Promise.resolve();
          },
          onmessage: (event) => {
            if (!event.event || event.event === "ready") return;
            let data: Record<string, unknown> = {};
            try {
              data = JSON.parse(event.data) as Record<string, unknown>;
            } catch {
              return;
            }
            if (event.id) this.lastEventId = event.id;
            const message: RealtimeMessage = { id: event.id || undefined, type: event.event, data };
            this.emit(message);
            this.channel?.postMessage(message);
          },
          onerror: (error: unknown) => {
            throw error;
          },
        });
      } catch {
        // reconnect below
      }
      if (this.isStopped() || controller.signal.aborted) return;
      const delay = opened.value ? 0 : (RETRY_MS[Math.min(attempt, RETRY_MS.length - 1)] ?? 30000);
      attempt += 1;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
}
