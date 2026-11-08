// Coding-agent fixtures: repo-coder (Pi in a Docker sandbox, defined in code) next to the sample agents, the bridge's
// capabilities and coding-agent list, a Pi-shaped run (reasoning, a file written, an edit, a failing shell command,
// the answer) and the report it left as an artefact; plus MSW handlers for them.
import type { AgentOS } from "@agnostic/api";
import { http, HttpResponse } from "msw";

import piRun from "./fixtures/coding-run-pi.json";
import agentSchema from "./fixtures/studio-schema-agent.json";
import { GATEWAY, sampleAgents } from "./operate";

export const CODING_AGENT_ID = "repo-coder";
export const CODING_SESSION_ID = "ses_code_1";
export const CODING_RUN_ID = "run_code_1";

/** How the agent schema describes the coding-agent marker (`x-agnostic-coding-agent`). */
export const sampleCodingAgentSchema: unknown = agentSchema["x-agnostic-coding-agent"];

/** The run's events, in the shapes the bridge's Pi adapter emits. */
export const samplePiRunEvents: Record<string, unknown>[] = piRun;

export const sampleCodingAgentSummary: AgentOS.AgentResponse = {
  id: CODING_AGENT_ID,
  name: "Repo coder",
  is_component: false,
  metadata: { sdk: "pi" },
};

export const sampleCodingSandbox = {
  provider: "docker" as const,
  image: "agnostic-coding:0.1.0",
  network: "isolated",
  cpus: 2,
  memory_mb: 2048,
  turn_timeout_s: 900,
};

export const sampleCodingAgents = {
  items: [
    {
      id: CODING_AGENT_ID,
      name: "Repo coder",
      harness: "pi" as const,
      source: "code" as const,
      version: null,
      model: { id: "mock-coder", provider: "Agnostic" },
      sandbox: sampleCodingSandbox,
      tools: ["bash", "read", "write", "edit", "grep", "find", "ls"],
    },
  ],
};

/** A bridge that serves the coding-agent list. */
export const sampleBridgeCapabilities = {
  bridge_version: "0.3.0",
  api_version: "v1",
  endpoints: [
    "GET /agnostic/v1/artifacts",
    "GET /agnostic/v1/capabilities",
    "GET /agnostic/v1/coding-agents",
  ],
  features: { coding_agents: { enabled: true } },
};

/** A bridge from before coding agents. */
export const sampleBridgeCapabilitiesWithoutCoding = {
  bridge_version: "0.2.0",
  api_version: "v1",
  endpoints: ["GET /agnostic/v1/artifacts", "GET /agnostic/v1/capabilities"],
  features: {},
};

export const sampleCodingArtifact = {
  id: "art_code_report",
  storage_key: `${CODING_SESSION_ID}/art_report.md`,
  session_id: CODING_SESSION_ID,
  run_id: CODING_RUN_ID,
  component_kind: "agent",
  component_id: CODING_AGENT_ID,
  kind: "file",
  filename: "report.md",
  title: "report.md",
  content_type: "text/markdown",
  size: 98,
  sha256: "0".repeat(64),
  path: "outputs/report.md",
  source: "docker",
  producer: null,
  revision: 1,
  role: "output",
  created_at: "2026-11-08T09:30:00Z",
};

export function codingHandlers({ coding = true }: { coding?: boolean } = {}) {
  return [
    http.get(`${GATEWAY}/agnostic/v1/capabilities`, () =>
      HttpResponse.json(coding ? sampleBridgeCapabilities : sampleBridgeCapabilitiesWithoutCoding),
    ),
    http.get(`${GATEWAY}/agnostic/v1/coding-agents`, () =>
      coding
        ? HttpResponse.json(sampleCodingAgents)
        : HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
    ),
    http.get(`${GATEWAY}/agents`, () => HttpResponse.json([...sampleAgents, sampleCodingAgentSummary])),
  ];
}
