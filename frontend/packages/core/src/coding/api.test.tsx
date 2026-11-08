// Coding agents are asked for only when the bridge says it serves the list; the harness falls back from the list to
// the metadata marker to `metadata.sdk`; the badge names the harness and the sandbox.
import { configureApi } from "@agnostic/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { ReactNode } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { codingAgentsEnabled, codingHarnessOf, useCodingAgents, type CodingAgent } from "./api";
import { CodingAgentBadge } from "./badge";

const GATEWAY = "http://agnostic.test/api/v1/instances/:instance/os";
const repoCoder: CodingAgent = {
  id: "repo-coder",
  name: "Repo coder",
  harness: "pi",
  source: "code",
  version: null,
  model: { id: "mock-coder", provider: "Agnostic" },
  sandbox: {
    provider: "docker",
    image: "agnostic-coding:0.1.0",
    cpus: 2,
    memory_mb: 2048,
    network: "isolated",
  },
  tools: ["bash"],
};
const calls: string[] = [];

function handlers(endpoints: string[]) {
  return [
    http.get(`${GATEWAY}/agnostic/v1/capabilities`, () => HttpResponse.json({ endpoints, features: {} })),
    http.get(`${GATEWAY}/agnostic/v1/coding-agents`, () => {
      calls.push("coding-agents");
      return HttpResponse.json({ items: [repoCoder] });
    }),
  ];
}

const server = setupServer();

beforeAll(() => {
  configureApi({ baseUrl: "http://agnostic.test" });
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers();
  calls.length = 0;
});
afterAll(() => {
  server.close();
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useCodingAgents", () => {
  it("lists coding agents when the bridge serves the route", async () => {
    server.use(...handlers(["GET /agnostic/v1/capabilities", "GET /agnostic/v1/coding-agents"]));
    const { result } = renderHook(() => useCodingAgents("prod-agentos"), { wrapper });
    await waitFor(() => {
      expect(result.current.byId.get("repo-coder")?.harness).toBe("pi");
    });
    expect(result.current.enabled).toBe(true);
  });

  it("never asks a bridge that doesn't serve it", async () => {
    server.use(...handlers(["GET /agnostic/v1/capabilities"]));
    const { result } = renderHook(() => useCodingAgents("prod-agentos"), { wrapper });
    await waitFor(() => {
      expect(result.current.fetchStatus).toBe("idle");
    });
    // The capabilities answer has arrived and said no.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(result.current.enabled).toBe(false);
    expect(result.current.byId.size).toBe(0);
    expect(calls).toEqual([]);
  });

  it("treats a runtime without the bridge as having none", async () => {
    server.use(
      http.get(`${GATEWAY}/agnostic/v1/capabilities`, () =>
        HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
      ),
    );
    const { result } = renderHook(() => useCodingAgents("prod-agentos"), { wrapper });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(result.current.enabled).toBe(false);
    expect(calls).toEqual([]);
  });
});

describe("codingAgentsEnabled", () => {
  it("reads the feature switch or the endpoint list", () => {
    expect(codingAgentsEnabled(undefined)).toBe(false);
    expect(codingAgentsEnabled({ features: { coding_agents: { enabled: true } } })).toBe(true);
    expect(codingAgentsEnabled({ endpoints: ["GET /agnostic/v1/coding-agents"] })).toBe(true);
    expect(codingAgentsEnabled({ endpoints: ["GET /agnostic/v1/artifacts"] })).toBe(false);
  });
});

describe("codingHarnessOf", () => {
  it("prefers the bridge's list, then the marker, then metadata.sdk", () => {
    const agents = new Map([["repo-coder", repoCoder]]);
    expect(codingHarnessOf({ id: "repo-coder", family: "agents" }, agents)).toBe("pi");
    expect(
      codingHarnessOf({
        id: "studio-coder",
        family: "agents",
        metadata: { agnostic: { coding_agent: { harness: "opencode" } } },
      }),
    ).toBe("opencode");
    expect(codingHarnessOf({ id: "cli", family: "agents", metadata: { sdk: "pi" } })).toBe("pi");
    expect(codingHarnessOf({ id: "claude", family: "agents", metadata: { sdk: "claude" } })).toBeUndefined();
    expect(codingHarnessOf({ id: "team", family: "teams", metadata: { sdk: "pi" } })).toBeUndefined();
  });
});

describe("CodingAgentBadge", () => {
  it("names the harness and the sandbox", () => {
    render(<CodingAgentBadge harness="pi" sandbox={repoCoder.sandbox} />);
    const badge = screen.getByRole("button", { name: "Coding agent: Pi on Docker" });
    expect(badge.querySelector('[data-brand="pi"]')).not.toBeNull();
    expect(badge.querySelector('[data-brand="docker"]')).not.toBeNull();
  });
});
