// Studio sample data and handlers: the registry of staging-agentos, support-triage (v3 current, draft v4) and
// research-team, with a codegen stand-in that maps fields to lines the way the server does.
import type {
  CodeComponentOut,
  CodegenOut,
  ComponentDetailOut,
  ComponentRowOut,
  PublishCheckOut,
  RegistryEntryOut,
  RegistryOut,
  VersionOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import agentSchema from "./fixtures/studio-schema-agent.json";
import teamSchema from "./fixtures/studio-schema-team.json";
import workflowSchema from "./fixtures/studio-schema-workflow.json";

const T = "2026-11-02T09:00:00Z";
const PARAMETERS = { type: "object", properties: { order_id: { type: "string" } }, required: ["order_id"] };

function entry(
  partial: Partial<RegistryEntryOut> & Pick<RegistryEntryOut, "type" | "name">,
): RegistryEntryOut {
  return {
    id: null,
    description: null,
    blurb: `${partial.type} registered in registry.py.`,
    meta: "",
    status: "registered",
    details: [],
    code: null,
    code_label: null,
    requires_approval: false,
    approval_type: null,
    studio_available: true,
    availability: {
      kind: "registered",
      title: "Registered.",
      text: "Studio can select it when building agents, teams and workflows.",
    },
    functions: [],
    source: null,
    used_by_count: 0,
    config_value: null,
    ...partial,
  };
}

const AVAILABLE = {
  kind: "available" as const,
  title: "Available in Studio.",
  text: "Passed to Registry(tools=[...]), so builders can attach it.",
};

export const studioRegistry: RegistryEntryOut[] = [
  entry({
    type: "tool",
    name: "kb_lookup",
    meta: "app.tools.kb.kb_lookup",
    availability: AVAILABLE,
    used_by_count: 1,
    config_value: [{ name: "kb_lookup", parameters: PARAMETERS }],
  }),
  entry({
    type: "tool",
    name: "refund_customer",
    meta: "app.tools.billing.refund_customer · @approval",
    description: "Issues a refund through the payments API.",
    blurb: "Issues a refund through the payments API.",
    requires_approval: true,
    availability: AVAILABLE,
    used_by_count: 1,
    details: [{ key: "class_path", value: "agno.tools.function.Function" }],
    code: JSON.stringify(PARAMETERS, null, 2),
    code_label: "parameters",
    config_value: [{ name: "refund_customer", parameters: PARAMETERS, requires_confirmation: true }],
  }),
  entry({
    type: "tool",
    name: "create_ticket",
    status: "discovered",
    studio_available: false,
    blurb: "Found on a component that is defined in code.",
    availability: {
      kind: "unavailable",
      title: "Not available in Studio.",
      text: "AgentOS discovered it so a component defined in code can be rebuilt, but only tools passed to Registry(tools=[...]) can be added to new agents.",
    },
    config_value: [{ name: "create_ticket", parameters: PARAMETERS }],
  }),
  entry({
    type: "model",
    name: "mock-precise",
    meta: "provider Agnostic · model_id mock-precise",
    config_value: { id: "mock-precise", provider: "Agnostic" },
  }),
  entry({
    type: "model",
    name: "mock-creative",
    meta: "provider Agnostic · model_id mock-creative",
    config_value: { id: "mock-creative", provider: "Agnostic" },
  }),
  entry({ type: "schema", name: "TriageResult", meta: "BaseModel · 3 fields", config_value: "TriageResult" }),
  entry({
    type: "agent",
    name: "kb-researcher",
    id: "kb-researcher",
    config_value: { type: "agent", agent_id: "kb-researcher" },
  }),
];

export function studioRegistryOut(): RegistryOut {
  const counts: Record<string, number> = {};
  for (const item of studioRegistry) counts[item.type] = (counts[item.type] ?? 0) + 1;
  return {
    instance: "staging-agentos",
    entries: studioRegistry,
    counts,
    total: studioRegistry.length,
    bridge: true,
  };
}

function version(partial: Partial<VersionOut> & Pick<VersionOut, "version" | "stage">): VersionOut {
  return {
    tag: partial.stage === "draft" ? `v${String(partial.version)} draft` : `v${String(partial.version)}`,
    current: false,
    label: null,
    notes: null,
    created_at: T,
    updated_at: T,
    revision: `r${String(partial.version)}`,
    author_name: "Daniel Okafor",
    updated_by_name: "Daniel Okafor",
    saved_at: T,
    published_by_name: null,
    published_at: null,
    eval_status: null,
    change_summary: null,
    based_on_version: null,
    promoted_from: null,
    links: [],
    config: null,
    ...partial,
  };
}

export const triageV3 = {
  id: "support-triage",
  name: "support-triage",
  model: { id: "mock-creative", provider: "Agnostic" },
  instructions: ["Classify by product area and urgency.", "Search the help center before answering."],
  tools: [{ name: "kb_lookup", parameters: PARAMETERS }],
  markdown: true,
};

export function triageDetail(): ComponentDetailOut {
  const current = version({
    version: 3,
    stage: "published",
    current: true,
    config: triageV3,
    published_by_name: "Daniel Okafor",
    published_at: T,
    eval_status: "passed",
  });
  const draft = version({
    version: 4,
    stage: "draft",
    based_on_version: 3,
    config: { ...triageV3, model: { id: "mock-precise", provider: "Agnostic" } },
  });
  return {
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
      { ...draft, config: null },
      { ...current, config: null },
    ],
    draft,
    current,
    owner_group_id: null,
    labels: [],
  };
}

export const researchTeam = {
  id: "research-team",
  name: "research-team",
  model: { id: "mock-precise", provider: "Agnostic" },
  mode: "coordinate",
  members: [
    { type: "agent", agent_id: "kb-researcher" },
    { type: "agent", agent_id: "summarizer" },
  ],
};

export function teamDetail(): ComponentDetailOut {
  const current = version({ version: 2, stage: "published", current: true, config: researchTeam });
  const draft = version({
    version: 3,
    stage: "draft",
    based_on_version: 2,
    config: researchTeam,
    links: [{ link_kind: "member", child_component_id: "summarizer", child_version: 4 }],
  });
  return {
    ...triageDetail(),
    component: {
      ...triageDetail().component,
      id: "research-team",
      kind: "team",
      name: "research-team",
      current_version: 2,
    },
    versions: [
      { ...draft, config: null },
      { ...current, config: null },
    ],
    draft,
    current,
  };
}

/** A small stand-in for the generator: one kwarg per line, so spans and marks are easy to assert. */
export function fakeCodegen(
  kind: string,
  config: Record<string, unknown>,
  base: Record<string, unknown> | null,
): CodegenOut {
  const lines = [
    `from agno.${kind} import ${kind === "team" ? "Team" : "Agent"}`,
    "",
    `component = ${kind === "team" ? "Team" : "Agent"}(`,
  ];
  const spans: CodegenOut["spans"] = {};
  const marks: CodegenOut["marks"] = {};
  for (const [key, value] of Object.entries(config)) {
    const rendered = key === "mode" ? `TeamMode.${String(value)}` : JSON.stringify(value);
    lines.push(`    ${key}=${rendered},`);
    const line = lines.length;
    spans[key] = { line, col_start: 4, col_end: 4 + key.length + 1 + rendered.length, end_line: line };
    if (base && JSON.stringify(base[key]) !== JSON.stringify(value))
      marks[String(line)] = key in base ? "modified" : "added";
  }
  lines.push(")");
  return {
    code: `${lines.join("\n")}\n`,
    filename: `${kind}s/component.py`,
    spans,
    marks,
    notes: [],
    ruff: { available: true, status: "ruff · 0 errors", formatted: false, messages: [] },
    base_code: null,
  };
}

export function publishCheck(blocked: boolean): PublishCheckOut {
  return {
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
    gates: [
      {
        gate_id: "gate_1",
        dataset_id: "eds_1",
        dataset_name: "billing-tickets-v2",
        eval_type: "accuracy",
        min_average: 8.5,
        value: blocked ? 8.4 : 8.9,
        batch_id: "evb_1",
        state: blocked ? "would_block" : "passes",
        consequence: blocked
          ? "v4 draft (8.40) would be blocked from publishing."
          : "v4 draft (8.90) meets the minimum of 8.5.",
        blocks: blocked,
      },
    ],
    blocked_by_gates: blocked,
    hold: { held: false, reason: null, write_back: null, link: null },
    can_publish: true,
    can_override: true,
    outcome: "v4 becomes current on staging-agentos, replacing v3; the API serves it from the next request.",
    summary: "model mock-creative → mock-precise",
    changes: [],
  };
}

export const studioRows: ComponentRowOut[] = [
  {
    component: triageDetail().component,
    editable: true,
    latest_version: 4,
    draft_version: 4,
    draft_updated_at: T,
    owner_group_id: null,
    labels: [],
    runs_7d: null,
  },
  {
    component: {
      ...triageDetail().component,
      id: "kb-researcher",
      name: "kb-researcher",
      source: "code",
      current_version: null,
    },
    editable: false,
    latest_version: null,
    draft_version: null,
    draft_updated_at: null,
    owner_group_id: null,
    labels: [],
    runs_7d: null,
  },
];

/** kb-researcher, defined in the runtime's code, as Studio reads it through the bridge. */
export function kbResearcherCode(): CodeComponentOut {
  const row = studioRows[1];
  if (!row) throw new Error("no code row");
  return {
    component: row.component,
    config: {
      id: "kb-researcher",
      name: "kb-researcher",
      model: { id: "mock-precise", provider: "Agnostic" },
      instructions: ["Search the knowledge base first."],
    },
    source: { module: "app.agents.kb_researcher", file: "/srv/app/agents/kb_researcher.py", line: 7 },
    unavailable: null,
  };
}

/** Requests the Studio handlers saw, for assertions. */
export type StudioCalls = {
  /** Bodies of component PATCHes (rename, labels), with the component they went to. */
  patches?: { id: string; body: Record<string, unknown> }[];
  saves: Record<string, unknown>[];
  publishes: Record<string, unknown>[];
  promotions: Record<string, unknown>[];
};

export function studioHandlers(calls: StudioCalls = { saves: [], publishes: [], promotions: [] }) {
  const base = `${API}/instances/:instance/studio`;
  return [
    http.get(`${API}/studio/schema/:kind`, ({ params }) =>
      HttpResponse.json(
        params.kind === "team" ? teamSchema : params.kind === "workflow" ? workflowSchema : agentSchema,
      ),
    ),
    http.get(`${API}/studio/templates`, () => HttpResponse.json([])),
    http.get(`${base}/components/:componentId/source`, () => HttpResponse.json({ bound: false })),
    http.get(`${base}/registry`, () => HttpResponse.json(studioRegistryOut())),
    http.get(`${base}/registry/:type/:name`, ({ params }) => {
      const found = studioRegistry.find((item) => item.type === params.type && item.name === params.name);
      if (!found)
        return HttpResponse.json(
          { title: "Not found", status: 404, detail: "No such entry" },
          { status: 404 },
        );
      return HttpResponse.json({
        entry: found,
        used_by:
          found.used_by_count > 0
            ? [
                {
                  component_id: "support-triage",
                  component_kind: "agent",
                  component_name: "support-triage",
                  versions: ["v3", "v4 draft"],
                  versions_text: "v3 · v4 draft",
                },
              ]
            : [],
      });
    }),
    http.get(`${base}/components`, ({ request }) => {
      const kind = new URL(request.url).searchParams.get("kind") ?? "agent";
      return HttpResponse.json(kind === "agent" ? studioRows : []);
    }),
    http.get(`${base}/code-components/:kind/:id`, ({ params }) =>
      params.kind === "agent" && params.id === "kb-researcher"
        ? HttpResponse.json(kbResearcherCode())
        : HttpResponse.json({ title: "Not found", status: 404, detail: "Not in code" }, { status: 404 }),
    ),
    http.get(`${base}/components/:id`, ({ params }) =>
      params.id === "research-team"
        ? HttpResponse.json(teamDetail())
        : params.id === "support-triage"
          ? HttpResponse.json(triageDetail())
          : HttpResponse.json({ title: "Not found", status: 404, detail: "Not stored" }, { status: 404 }),
    ),
    http.patch(`${base}/components/:id`, async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>;
      (calls.patches ??= []).push({ id: String(params.id), body });
      const detail = params.id === "research-team" ? teamDetail() : triageDetail();
      const name = typeof body.name === "string" ? body.name : detail.component.name;
      return HttpResponse.json({
        ...detail,
        component: { ...detail.component, name },
        draft: detail.draft
          ? { ...detail.draft, config: { ...detail.draft.config, name }, revision: "r-renamed" }
          : detail.draft,
      });
    }),
    http.get(`${base}/components/:id/diff`, () =>
      HttpResponse.json({
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
      }),
    ),
    http.patch(`${base}/components/:id/configs/:version`, async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.saves.push(body);
      const detail = params.id === "research-team" ? teamDetail() : triageDetail();
      return HttpResponse.json({
        ...detail.draft,
        config: body.config,
        revision: `r-saved-${String(calls.saves.length)}`,
      });
    }),
    http.get(`${base}/components/:id/configs/:version/code`, () =>
      HttpResponse.json({
        code_backed: false,
        code: null,
        stale: false,
        updated_by_name: null,
        updated_at: null,
      }),
    ),
    http.post(`${base}/codegen`, async ({ request }) => {
      const body = (await request.json()) as {
        kind: string;
        config: Record<string, unknown>;
        base_config: Record<string, unknown> | null;
      };
      return HttpResponse.json(fakeCodegen(body.kind, body.config, body.base_config));
    }),
    http.get(`${base}/components/:id/publish-check`, () => HttpResponse.json(publishCheck(true))),
    http.post(`${base}/components/:id/configs/:version/publish`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.publishes.push(body);
      return HttpResponse.json({
        version: { ...triageDetail().draft, stage: "published", current: true, eval_status: "overridden" },
        outcome:
          "v4 becomes current on staging-agentos, replacing v3; the API serves it from the next request.",
        overridden: Boolean(body.override_reason),
        gates: publishCheck(true).gates,
      });
    }),
    http.post(`${base}/components/:id/promotions`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.promotions.push(body);
      const blocked = calls.promotions.length === 1;
      return HttpResponse.json(
        {
          id: `prm_${String(calls.promotions.length)}`,
          from_instance: "ins_staging",
          to_instance: "ins_prod",
          component_id: "support-triage",
          component_kind: "agent",
          from_version: 3,
          to_version: null,
          include_children: true,
          status: blocked ? "blocked" : "dry_run",
          report: blocked
            ? {
                ok: false,
                summary: "Blocked: tool `refund_customer` isn't registered on the target.",
                missing: [{ type: "tool", name: "refund_customer", paths: ["tools[1]"] }],
                children: [],
              }
            : {
                ok: true,
                summary: "All 3 registry references exist on the target.",
                missing: [],
                children: [],
              },
          created_by_name: "Daniel Okafor",
          created_at: T,
          applied_at: null,
        },
        { status: 201 },
      );
    }),
  ];
}
