import { afterEach, describe, expect, it, vi } from "vitest";

import { gatewayFetch, instanceRequest, setInstanceRoutes } from "./index";

const FUTURE = new Date(Date.now() + 5 * 60_000).toISOString();

function stubFetch(handler: (url: string, init: RequestInit) => Response) {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init: RequestInit = {}) => {
      calls.push({ url: input, init });
      return Promise.resolve(handler(input, init));
    }),
  );
  return calls;
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  setInstanceRoutes([]);
});

describe("instanceRequest", () => {
  it("goes through the gateway unless the instance is in direct mode", async () => {
    setInstanceRoutes([{ id: "ins_1", slug: "prod", network_mode: "gateway", browser_url: "https://prod" }]);
    const target = await instanceRequest("prod", "/agents", "GET");
    expect(target).toMatchObject({
      url: "/api/v1/instances/prod/os/agents",
      credentials: "same-origin",
      direct: false,
    });
  });

  it("calls a direct-mode runtime with a cached short-lived token", async () => {
    setInstanceRoutes([
      { id: "ins_2", slug: "edge", network_mode: "direct", browser_url: "https://edge.example/" },
    ]);
    const calls = stubFetch(() =>
      json({ token: "jwt-1", expires_at: FUTURE, base_url: "https://edge.example/" }),
    );

    const first = await instanceRequest("edge", "agents/triage/runs", "POST", {
      Accept: "text/event-stream",
    });
    const second = await instanceRequest("edge", "sessions", "GET");

    expect(first.url).toBe("https://edge.example/agents/triage/runs");
    expect(first.credentials).toBe("omit");
    expect(first.headers.get("Authorization")).toBe("Bearer jwt-1");
    expect(first.headers.get("Accept")).toBe("text/event-stream");
    expect(second.headers.get("Authorization")).toBe("Bearer jwt-1");
    expect(calls.map((call) => call.url)).toEqual(["/api/v1/instances/edge/token"]);
  });

  it("retries a direct call once with a fresh token after a 401", async () => {
    setInstanceRoutes([
      { id: "ins_3", slug: "edge2", network_mode: "direct", browser_url: "https://edge2.example" },
    ]);
    let tokens = 0;
    let runtimeCalls = 0;
    const calls = stubFetch((url) => {
      if (url.endsWith("/token")) {
        tokens += 1;
        return json({
          token: `jwt-${String(tokens)}`,
          expires_at: FUTURE,
          base_url: "https://edge2.example",
        });
      }
      runtimeCalls += 1;
      return runtimeCalls === 1 ? json({ detail: "expired" }, 401) : json({ ok: true });
    });

    const response = await gatewayFetch("edge2", "health");

    expect(response.status).toBe(200);
    const runtime = calls.filter((call) => call.url.startsWith("https://edge2.example"));
    expect(runtime.map((call) => new Headers(call.init.headers).get("Authorization"))).toEqual([
      "Bearer jwt-1",
      "Bearer jwt-2",
    ]);
  });
});
