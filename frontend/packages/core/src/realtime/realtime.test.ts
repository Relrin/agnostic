import { approvalsCountQueryKey, configureApi } from "@agnostic/api";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { RealtimeClient, type RealtimeMessage } from "./events-client";
import { applyRealtimeEvent } from "./provider";

beforeAll(() => {
  configureApi({ baseUrl: "http://agnostic.test" });
});

function events(body: string): Response {
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

async function until(check: () => boolean): Promise<void> {
  const started = Date.now();
  while (!check()) {
    if (Date.now() - started > 2000) throw new Error("timed out");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

describe("RealtimeClient", () => {
  const clients: RealtimeClient[] = [];
  afterEach(() => {
    for (const client of clients.splice(0)) client.stop();
  });

  it("leads, delivers events, and reconnects with Last-Event-ID", async () => {
    const requests: Headers[] = [];
    const fetchImpl = vi.fn((_: RequestInfo | URL, init?: RequestInit) => {
      requests.push(new Headers(init?.headers));
      return Promise.resolve(
        requests.length === 1
          ? events(
              'event: ready\ndata: {"instances":["ins_a"]}\n\n' +
                'id: 01J1\nevent: approvals.count\ndata: {"count":3,"instance_id":"ins_a"}\n\n',
            )
          : (new Promise<Response>(() => undefined) as unknown as Response),
      );
    });
    const client = new RealtimeClient({ fetch: fetchImpl as unknown as typeof fetch });
    clients.push(client);
    const received: RealtimeMessage[] = [];
    client.subscribe((message) => received.push(message));
    client.start();
    await until(() => received.length === 1);
    expect(client.leader).toBe(true);
    expect(received[0]).toEqual({
      id: "01J1",
      type: "approvals.count",
      data: { count: 3, instance_id: "ins_a" },
    });
    await until(() => requests.length === 2);
    expect(requests[1]?.get("Last-Event-ID")).toBe("01J1");
  });
});

describe("applyRealtimeEvent", () => {
  it("updates the approvals badge in place and invalidates access on access.changed", () => {
    const client = new QueryClient();
    applyRealtimeEvent(client, {
      id: "1",
      type: "approvals.count",
      data: { count: 4, instance_id: "ins_a" },
    });
    expect(client.getQueryData(approvalsCountQueryKey({ path: { instance: "ins_a" } }))).toEqual({
      instance_id: "ins_a",
      count: 4,
      available: true,
    });
    const spy = vi.spyOn(client, "invalidateQueries");
    applyRealtimeEvent(client, { id: "2", type: "access.changed", data: {} });
    expect(spy).toHaveBeenCalledOnce();
  });
});
