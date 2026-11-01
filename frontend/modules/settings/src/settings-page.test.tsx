import { API, p01Handlers, PROD, renderPage } from "@agnostic/testing";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { SettingsPage } from "./settings-page";

const config = {
  instance_id: PROD,
  fetched_at: "2026-11-01T09:00:00Z",
  os_id: "prod-os",
  name: "prod-agentos",
  description: null,
  available_models: [],
  databases: ["prod-db", "vector-db"],
  os_database: "prod-db",
  interfaces: [{ type: "slack", route: "/slack", version: "1" }],
  agents: [],
  teams: [],
  workflows: [],
  sections: { queue: { durable: true } },
};
const handlers = [
  ...p01Handlers(),
  http.get(`${API}/instances/:instance/config`, () => HttpResponse.json(config)),
];
const server = setupServer(...handlers);

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...handlers);
});
afterAll(() => {
  server.close();
});

describe("SettingsPage", () => {
  it("shows the connection and the capability matrix", async () => {
    renderPage(SettingsPage, { path: "/i/$instance/settings", url: "/i/prod-agentos/settings" });
    expect(await screen.findByText("Settings · prod-agentos")).toBeInTheDocument();
    expect(screen.getByText("http://prod-agentos.internal:7777")).toBeInTheDocument();
    expect(await screen.findByText("Per-user permissions (JWT authorization enforced)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Test connection" })).toBeInTheDocument();
  });

  it("renders the runtime's databases from /config", async () => {
    renderPage(SettingsPage, {
      path: "/i/$instance/settings/$section",
      url: "/i/prod-agentos/settings/databases",
    });
    expect(await screen.findByText("vector-db")).toBeInTheDocument();
    expect(screen.getByText("OS database")).toBeInTheDocument();
    expect(await screen.findAllByRole("button", { name: "Migrate" })).toHaveLength(2);
  });
});
