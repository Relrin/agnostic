// RunStream over a fake gateway: submit, a drop mid-stream, /resume with last_event_index, cancel.
import { configureApi } from "@agnostic/api";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { agentCompleted, agentContinued, agentPaused } from "./__fixtures__/streams";
import type { RunEvent } from "./events";
import { RunStream } from "./run-stream";

function sse(events: readonly RunEvent[]): string {
  return events.map((event) => `event: ${event.event}\ndata: ${JSON.stringify(event)}\n\n`).join("");
}

function streamResponse(body: string): Response {
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

type Call = { url: string; body: string };

function fakeGateway(responses: readonly (() => Response)[]) {
  const calls: Call[] = [];
  let index = 0;
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = init?.body;
    calls.push({
      url: input instanceof Request ? input.url : input.toString(),
      body:
        body instanceof URLSearchParams
          ? body.toString()
          : body instanceof FormData
            ? "multipart"
            : typeof body === "string"
              ? body
              : "",
    });
    const next = responses[index] ?? responses.at(-1);
    index += 1;
    if (!next) throw new Error("no response configured");
    return Promise.resolve(next());
  });
  return { calls, fetch: fetchImpl as unknown as typeof fetch };
}

async function until(check: () => boolean, timeout = 2000): Promise<void> {
  const started = Date.now();
  while (!check()) {
    if (Date.now() - started > timeout) throw new Error("timed out");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

const TARGET = { instance: "prod-agentos", family: "agents", componentId: "support-triage" } as const;

beforeAll(() => {
  configureApi({ baseUrl: "http://agnostic.test" });
});

afterEach(() => {
  sessionStorage.clear();
});

describe("RunStream", () => {
  it("submits in the background and streams a run to completion", async () => {
    const gateway = fakeGateway([() => streamResponse(sse(agentCompleted))]);
    const stream = new RunStream(TARGET, {}, { fetch: gateway.fetch, retryDelays: [] });
    await stream.submit({ message: "where is my order?" });
    expect(stream.getState()).toMatchObject({
      status: "completed",
      content: "Done. Order ord_1001: shipped",
      phase: "closed",
    });
    expect(gateway.calls[0]?.url).toBe(
      "http://agnostic.test/api/v1/instances/prod-agentos/os/agents/support-triage/runs",
    );
    expect(gateway.calls[0]?.body).toBe("multipart");
  });

  it("resumes from the last event index when the stream drops mid-run", async () => {
    const gateway = fakeGateway([
      () => streamResponse(sse(agentCompleted.slice(0, 4))),
      () => streamResponse(`event: catch_up\ndata: {}\n\n${sse(agentCompleted.slice(2))}`),
    ]);
    const stream = new RunStream(TARGET, {}, { fetch: gateway.fetch, retryDelays: [0, 0] });
    await stream.submit({ message: "where is my order?", sessionId: "ses_7f3a91c2" });
    await until(() => stream.getState().status === "completed");
    expect(gateway.calls[1]?.url).toBe(
      "http://agnostic.test/api/v1/instances/prod-agentos/os/agents/support-triage/runs/run_9f2c41/resume",
    );
    expect(new URLSearchParams(gateway.calls[1]?.body).get("last_event_index")).toBe("3");
    expect(new URLSearchParams(gateway.calls[1]?.body).get("session_id")).toBe("ses_7f3a91c2");
    // Events 2 and 3 came twice; the content didn't.
    expect(stream.getState().content).toBe("Done. Order ord_1001: shipped");
  });

  it("survives a refresh: the active run is persisted and can be resumed", async () => {
    const gateway = fakeGateway([() => streamResponse(sse(agentCompleted.slice(0, 2)))]);
    const stream = new RunStream(TARGET, {}, { fetch: gateway.fetch, retryDelays: [60_000] });
    await stream.submit({ message: "hello" });
    expect(RunStream.restorable("prod-agentos")).toEqual([
      expect.objectContaining({ runId: "run_9f2c41", target: TARGET, input: "hello" }),
    ]);
    stream.dispose();
    expect(RunStream.restorable("prod-agentos")).toEqual([]);
  });

  it("replays from the start after an approval decision continued the run", async () => {
    const gateway = fakeGateway([
      () => streamResponse(sse(agentPaused)),
      () => streamResponse(sse(agentContinued)),
    ]);
    const stream = new RunStream(TARGET, {}, { fetch: gateway.fetch, retryDelays: [] });
    await stream.submit({ message: "refund 49 for cus_8812" });
    expect(stream.getState().status).toBe("paused");
    await stream.resume({ fromStart: true });
    expect(new URLSearchParams(gateway.calls[1]?.body).has("last_event_index")).toBe(false);
    expect(stream.getState()).toMatchObject({ status: "completed", input: "refund 49 for cus_8812" });
    expect(stream.getState().tools).toHaveLength(1);
  });

  it("gives up after the last retry and says so", async () => {
    const gateway = fakeGateway([() => streamResponse(sse(agentCompleted.slice(0, 1)))]);
    const stream = new RunStream(TARGET, {}, { fetch: gateway.fetch, retryDelays: [0] });
    await stream.submit({ message: "hi" });
    await until(() => stream.getState().phase === "closed");
    expect(stream.getState().error?.type).toBe("connection");
  });

  it("turns a refused submit into an error state", async () => {
    const gateway = fakeGateway([
      () =>
        new Response(
          JSON.stringify({
            type: "x",
            title: "Forbidden",
            status: 403,
            code: "scope_missing",
            explanation: "You need agents:run.",
          }),
          { status: 403, headers: { "Content-Type": "application/problem+json" } },
        ),
    ]);
    const stream = new RunStream(TARGET, {}, { fetch: gateway.fetch, retryDelays: [0] });
    await stream.submit({ message: "hi" });
    expect(stream.getState()).toMatchObject({
      status: "error",
      error: { message: "You need agents:run." },
      phase: "closed",
    });
    expect(gateway.calls).toHaveLength(1);
  });
});
