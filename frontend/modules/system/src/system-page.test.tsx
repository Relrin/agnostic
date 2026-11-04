import { API, sampleOrgHandlers, renderPage } from "@agnostic/testing";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { SystemPage } from "./system-page";

const status = {
  environment: "production",
  versions: {
    server: "1.0.0",
    python: "3.15.2",
    database: "postgresql 18.1",
    cache: "valkey 8.1.4",
    modules: { audit: "0.1.0", system: "0.1.0" },
  },
  queues: [{ queue: "default", waiting: 3, running: 1, failed: 2, oldest_wait_seconds: 42 }],
  cache: { backend: "redis", hits: 90, misses: 10, hit_ratio: 0.9 },
  instances: [
    {
      id: "ins_1",
      slug: "prod-agentos",
      display_name: "prod-agentos",
      status: "connected",
      last_seen_at: new Date().toISOString(),
      latency_ms: 38,
      network_mode: "gateway",
    },
  ],
  items: [
    { group: "Audit", name: "SIEM: Splunk", state: "error", detail: "connection refused", facts: {} },
    { group: "Notifications", name: "Deliveries", state: "ok", detail: "every delivery went out", facts: {} },
  ],
};
const failed = [
  {
    id: 41,
    queue: "default",
    task: "notifications.deliver",
    attempts: 3,
    failed_at: null,
    argument_names: ["id"],
  },
];

let retried: string[] = [];
const handlers = () => [
  ...sampleOrgHandlers(),
  http.get(`${API}/system/status`, () => HttpResponse.json(status)),
  http.get(`${API}/system/jobs/failed`, () => HttpResponse.json(failed)),
  http.post(`${API}/system/jobs/:id/retry`, ({ params }) => {
    retried.push(String(params.id));
    return new HttpResponse(null, { status: 204 });
  }),
  http.post(`${API}/system/checks`, () =>
    HttpResponse.json([
      { name: "database", ok: true, detail: "ok", facts: { version: "18.1" } },
      { name: "instance prod-agentos", ok: false, detail: "unreachable: timed out", facts: {} },
    ]),
  ),
];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  retried = [];
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

function open() {
  return renderPage(SystemPage, { path: "/org/system", url: "/org/system" });
}

describe("SystemPage", () => {
  it("shows versions, queues, backlogs and instance polling", async () => {
    open();
    expect(await screen.findByText("postgresql 18.1")).toBeInTheDocument();
    expect(screen.getByText("valkey 8.1.4")).toBeInTheDocument();
    const queues = screen.getByRole("table", { name: "Job queues" });
    expect(within(queues).getByText("default")).toBeInTheDocument();
    expect(screen.getByText("connection refused")).toBeInTheDocument();
    expect(screen.getByText(/90\.0% hits/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("table", { name: "Instance polling" })).getByText("38 ms"),
    ).toBeInTheDocument();
  });

  it("retries a failed job", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Retry notifications.deliver #41" }));
    await waitFor(() => {
      expect(retried).toEqual(["41"]);
    });
  });

  it("runs the endpoint checks on demand", async () => {
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Check endpoints" }));
    const table = await screen.findByRole("table", { name: "Endpoint checks" });
    expect(within(table).getByText("unreachable: timed out")).toBeInTheDocument();
    expect(within(table).getByText("version=18.1")).toBeInTheDocument();
  });
});
