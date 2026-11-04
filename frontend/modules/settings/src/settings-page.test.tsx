import { API, notificationsHandlers, sampleOrgHandlers, PROD, renderPage } from "@agnostic/testing";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  ...sampleOrgHandlers(),
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

const key = (kid: string, status: "active" | "next") => ({
  kid,
  alg: "RS256",
  status,
  public_pem: "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----",
  created_at: "2026-11-01T09:00:00Z",
  activated_at: null,
});
const stagedKeys = {
  keys: [key("kid-active-000000000", "active"), key("kid-next-0000000000", "next")],
  issuer: "http://agnostic.test",
  audience: "prod-os",
  env_snippet: null,
  python_snippet: null,
  jwks_path: `/.well-known/agnostic/instances/${PROD}/jwks.json`,
  rotation_note: "A next key is staged.",
};

describe("SettingsPage authorization", () => {
  it("asks before activating a staged key", async () => {
    const actions: unknown[] = [];
    server.use(
      http.get(`${API}/instances/:instance/keys/public`, () => HttpResponse.json(stagedKeys)),
      http.post(`${API}/instances/:instance/keys/rotate`, async ({ request }) => {
        actions.push(await request.json());
        return HttpResponse.json(stagedKeys);
      }),
    );
    const user = userEvent.setup();
    renderPage(SettingsPage, {
      path: "/i/$instance/settings/$section",
      url: "/i/prod-agentos/settings/authorization",
    });
    await user.click(await screen.findByRole("button", { name: "Activate next key" }));
    expect(await screen.findByRole("dialog", { name: "Activate the next key?" })).toBeInTheDocument();
    expect(actions).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(actions).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Activate next key" }));
    const dialog = await screen.findByRole("dialog", { name: "Activate the next key?" });
    await user.click(within(dialog).getByRole("button", { name: "Activate next key" }));
    await waitFor(() => {
      expect(actions).toEqual([{ action: "activate" }]);
    });
  });
});

describe("SettingsPage control sections", () => {
  it("lists org notification channels and the defaults", async () => {
    server.use(...notificationsHandlers());
    renderPage(SettingsPage, {
      path: "/i/$instance/settings/$section",
      url: "/i/prod-agentos/settings/notifications",
    });
    expect(await screen.findByText("Slack · billing-ops")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Enable Slack · billing-ops" })).toBeChecked();
    expect(await screen.findByRole("checkbox", { name: "Default Schedule failed by In app" })).toBeChecked();
  });

  it("shows the approval expiry policy", async () => {
    server.use(...notificationsHandlers());
    renderPage(SettingsPage, {
      path: "/i/$instance/settings/$section",
      url: "/i/prod-agentos/settings/approvals",
    });
    expect(
      await screen.findByRole("switch", { name: "Stop runs when their approval expires" }),
    ).not.toBeChecked();
  });
});
