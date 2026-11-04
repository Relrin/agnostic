// The Studio stub for the agent editor: support-triage on staging (v3 current, draft v4 switches the model), a
// publish check whose eval gate would block v4, and a publish that records its body.
import type { Page, Route } from "@playwright/test";

import agentSchema from "../../../../packages/testing/src/fixtures/studio-schema-agent.json" with { type: "json" };
import { T } from "../stubs";

const STUDIO = /\/api\/v1\/instances\/[^/]+\/studio\//;
const PARAMETERS = { type: "object", properties: { order_id: { type: "string" } }, required: ["order_id"] };

function entry(type: string, name: string, meta: string, configValue: unknown) {
  return {
    type,
    name,
    id: null,
    description: null,
    blurb: `${type} registered in registry.py.`,
    meta,
    status: "registered",
    details: [],
    code: null,
    code_label: null,
    requires_approval: false,
    approval_type: null,
    studio_available: true,
    availability: {
      kind: "available",
      title: "Available in Studio.",
      text: "Passed to Registry(tools=[...]), so builders can attach it.",
    },
    functions: [],
    source: null,
    used_by_count: 0,
    config_value: configValue,
  };
}

const REGISTRY = [
  entry("tool", "kb_lookup", "app.tools.kb.kb_lookup", [{ name: "kb_lookup", parameters: PARAMETERS }]),
  entry("model", "mock-precise", "provider Agnostic · model_id mock-precise", {
    id: "mock-precise",
    provider: "Agnostic",
  }),
  entry("model", "mock-creative", "provider Agnostic · model_id mock-creative", {
    id: "mock-creative",
    provider: "Agnostic",
  }),
];

const V3 = {
  id: "support-triage",
  name: "support-triage",
  model: { id: "mock-creative", provider: "Agnostic" },
  instructions: ["Classify by product area and urgency.", "Search the help center before answering."],
  tools: [{ name: "kb_lookup", parameters: PARAMETERS }],
  markdown: true,
};

function version(number: number, stage: string, config: Record<string, unknown>) {
  return {
    version: number,
    stage,
    tag: stage === "draft" ? `v${String(number)} draft` : `v${String(number)}`,
    current: stage === "published",
    label: null,
    notes: null,
    created_at: T,
    updated_at: T,
    revision: `r${String(number)}`,
    author_name: "Daniel Okafor",
    updated_by_name: "Daniel Okafor",
    saved_at: T,
    published_by_name: stage === "published" ? "Daniel Okafor" : null,
    published_at: stage === "published" ? T : null,
    eval_status: stage === "published" ? "passed" : null,
    change_summary: null,
    based_on_version: stage === "draft" ? number - 1 : null,
    promoted_from: null,
    links: [],
    config,
  };
}

const CURRENT = version(3, "published", V3);
const DRAFT = version(4, "draft", { ...V3, model: { id: "mock-precise", provider: "Agnostic" } });

const DETAIL = {
  component: {
    id: "support-triage",
    kind: "agent",
    name: "support-triage",
    description: null,
    current_version: 3,
    source: "studio",
    created_at: T,
    updated_at: T,
    deleted_at: null,
  },
  editable: true,
  versions: [
    { ...DRAFT, config: null },
    { ...CURRENT, config: null },
  ],
  draft: DRAFT,
  current: CURRENT,
  owner_group_id: null,
  labels: [],
};

const OUTCOME =
  "v4 becomes current on staging-agentos, replacing v3; the API serves it from the next request.";

const GATES = [
  {
    gate_id: "gate_1",
    dataset_id: "eds_1",
    dataset_name: "billing-tickets-v2",
    eval_type: "accuracy",
    min_average: 8.5,
    value: 8.4,
    batch_id: "evb_1",
    state: "would_block",
    consequence: "v4 draft (8.40) would be blocked from publishing.",
    blocks: true,
  },
];

const PUBLISH_CHECK = {
  version: 4,
  stage: "draft",
  validation: {
    ok: true,
    summary: "Valid.",
    layers: [
      { id: "shape", label: "Shape", status: "ok", hint: null, diagnostics: [] },
      { id: "registry", label: "Registry references", status: "ok", hint: null, diagnostics: [] },
      { id: "rules", label: "Studio rules", status: "ok", hint: null, diagnostics: [] },
      { id: "bridge", label: "agno strict load", status: "ok", hint: null, diagnostics: [] },
    ],
  },
  gates: GATES,
  blocked_by_gates: true,
  hold: { held: false, reason: null, write_back: null, link: null },
  can_publish: true,
  can_override: true,
  outcome: OUTCOME,
  summary: "model mock-creative → mock-precise",
  changes: [],
};

/** One kwarg per line, the way the server's generator lays an agent out. */
function codegen(config: Record<string, unknown>) {
  const lines = ["from agno.agent import Agent", "", "component = Agent("];
  const spans: Record<string, { line: number; col_start: number; col_end: number; end_line: number }> = {};
  for (const [key, value] of Object.entries(config)) {
    const rendered = JSON.stringify(value);
    lines.push(`    ${key}=${rendered},`);
    spans[key] = {
      line: lines.length,
      col_start: 4,
      col_end: 4 + key.length + 1 + rendered.length,
      end_line: lines.length,
    };
  }
  lines.push(")");
  return {
    code: `${lines.join("\n")}\n`,
    filename: "agents/support_triage.py",
    spans,
    marks: {},
    notes: [],
    ruff: { available: true, status: "ruff · 0 errors", formatted: false, messages: [] },
    base_code: null,
  };
}

export type Studio = { publishes: Record<string, unknown>[] };

export async function stubStudio(page: Page): Promise<Studio> {
  const state: Studio = { publishes: [] };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  await page.route(/\/api\/v1\/studio\/schema\/agent$/, (route) => json(route, agentSchema));
  await page.route(/\/api\/v1\/studio\/templates$/, (route) => json(route, []));
  await page.route(STUDIO, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^.*\/studio/, "");
    const method = route.request().method();
    if (path === "/sources/conflicts/count" || path.endsWith("/source")) return route.fallback();
    if (method === "GET" && path === "/registry")
      return json(route, {
        instance: "staging-agentos",
        entries: REGISTRY,
        counts: { tool: 1, model: 2 },
        total: REGISTRY.length,
        bridge: true,
      });
    if (method === "GET" && path === "/components/support-triage") return json(route, DETAIL);
    if (method === "GET" && path === "/components/support-triage/diff")
      return json(route, {
        component_id: "support-triage",
        from_version: 3,
        to_version: 4,
        changes: [
          {
            path: "model",
            field: "model",
            op: "changed",
            before: { id: "mock-creative" },
            after: { id: "mock-precise" },
          },
        ],
        counts: { added: 0, changed: 1, removed: 0 },
        summary: "model mock-creative → mock-precise",
        code_before: "",
        code_after: "",
        unified: "",
        lines_added: 1,
        lines_removed: 1,
      });
    if (method === "GET" && path.endsWith("/code"))
      return json(route, {
        code_backed: false,
        code: null,
        stale: false,
        updated_by_name: null,
        updated_at: null,
      });
    if (method === "PATCH" && path.startsWith("/components/support-triage/configs/")) {
      const body = route.request().postDataJSON() as { config: Record<string, unknown> };
      return json(route, { ...DRAFT, config: body.config, revision: "r4-saved" });
    }
    if (method === "POST" && path === "/codegen") {
      const body = route.request().postDataJSON() as { config: Record<string, unknown> };
      return json(route, codegen(body.config));
    }
    if (method === "GET" && path === "/components/support-triage/publish-check")
      return json(route, PUBLISH_CHECK);
    if (method === "POST" && path === "/components/support-triage/configs/4/publish") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      state.publishes.push(body);
      return json(route, {
        version: { ...DRAFT, stage: "published", current: true, eval_status: "overridden" },
        outcome: OUTCOME,
        overridden: Boolean(body.override_reason),
        gates: GATES,
      });
    }
    return json(route, { type: "x", title: "Not stubbed", status: 404, detail: `${method} ${path}` }, 404);
  });
  return state;
}
