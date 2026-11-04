import type { InstanceOut } from "@agnostic/api";
import { API, sampleOrgHandlers, renderPage, sampleInstances } from "@agnostic/testing";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ConnectWizard } from "./connect-wizard";
import { InstancesPage } from "./instances-page";

const [prod] = sampleInstances as [InstanceOut, ...InstanceOut[]];
const step = (id: string, label: string, status = "ok", detail = "", hint: string | null = null) => ({
  id,
  label,
  status,
  detail,
  hint,
});
const discovery = {
  os_id: "prod-os",
  name: "prod-agentos",
  agno_version: "3.1.12",
  os_version: "3.1.12",
  auth_mode: "jwt",
  user_isolation: true,
  agent_count: 6,
  team_count: 2,
  workflow_count: 2,
  mcp_enabled: false,
};
const wizardHandlers = [
  ...sampleOrgHandlers(),
  http.post(`${API}/instances/probe`, () =>
    HttpResponse.json({ ok: true, steps: [step("dns", "DNS"), step("connect", "Connect")], discovery }),
  ),
  http.post(`${API}/instances`, () =>
    HttpResponse.json({ instance: { ...prod, status: "pending" }, steps: [] }, { status: 201 }),
  ),
  http.get(`${API}/instances/:instance/keys/public`, () =>
    HttpResponse.json({
      keys: [
        {
          kid: "kid-123456789012345",
          alg: "RS256",
          status: "active",
          public_pem: "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----",
          created_at: "2026-11-01T09:00:00Z",
          activated_at: null,
        },
      ],
      issuer: "http://agnostic.test",
      audience: "prod-os",
      env_snippet: 'JWT_VERIFICATION_KEY="-----BEGIN PUBLIC KEY-----\\nabc"',
      python_snippet: 'audience="prod-os"',
      jwks_path: `/.well-known/agnostic/instances/${prod.id}/jwks.json`,
      rotation_note: "Rotate in two steps.",
    }),
  ),
];
const server = setupServer(...wizardHandlers);

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...wizardHandlers);
});
afterAll(() => {
  server.close();
});

describe("InstancesPage", () => {
  it("lists instances with status, version and latency", async () => {
    renderPage(InstancesPage, { path: "/instances" });
    expect(await screen.findByRole("link", { name: "prod-agentos" })).toBeInTheDocument();
    expect(screen.getAllByText("agno 3.1.12")).toHaveLength(2);
    expect(screen.getAllByText("38 ms")).toHaveLength(2);
  });

  it("invites to connect the first instance", async () => {
    server.use(http.get(`${API}/instances`, () => HttpResponse.json([])));
    renderPage(InstancesPage, { path: "/instances" });
    expect(await screen.findByText("Connect your first instance")).toBeInTheDocument();
  });
});

describe("ConnectWizard", () => {
  it("goes from endpoint to discovery, key and a passing test", async () => {
    server.use(
      http.post(`${API}/instances/:instance/test`, () =>
        HttpResponse.json({
          ok: true,
          instance: prod,
          steps: [step("auth", "Token", "ok", "AgentOS accepted a config:read token")],
          capabilities: [],
        }),
      ),
    );
    const user = userEvent.setup();
    renderPage(ConnectWizard, { path: "/instances/connect" });
    await user.type(await screen.findByLabelText("AgentOS endpoint"), "http://prod-agentos.internal:7777");
    await user.click(screen.getByRole("button", { name: "Discover" }));
    expect(await screen.findByText(/6 agents, 2 teams, 2/)).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("prod-agentos");
    await user.click(screen.getByRole("radio", { name: "Production" }));
    await user.click(screen.getByRole("button", { name: "Connect and create key pair" }));
    expect(await screen.findByText(/JWT_VERIFICATION_KEY=/)).toBeInTheDocument();
    expect(screen.getByText('audience="prod-os"')).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Test connection" }));
    expect(await screen.findByText("prod-agentos is connected")).toBeInTheDocument();
  });

  it("shows which discovery step failed and what to do", async () => {
    server.use(
      http.post(`${API}/instances/probe`, () =>
        HttpResponse.json({
          ok: false,
          steps: [step("dns", "DNS", "failed", "Can't resolve nowhere.invalid", "Check the hostname.")],
          discovery: null,
        }),
      ),
    );
    const user = userEvent.setup();
    renderPage(ConnectWizard, { path: "/instances/connect" });
    await user.type(await screen.findByLabelText("AgentOS endpoint"), "http://nowhere.invalid");
    await user.click(screen.getByRole("button", { name: "Discover" }));
    expect(await screen.findByText("Can't resolve nowhere.invalid")).toBeInTheDocument();
    expect(screen.getByText("Check the hostname.")).toBeInTheDocument();
    expect(screen.getByLabelText("Failed")).toBeInTheDocument();
  });
});
