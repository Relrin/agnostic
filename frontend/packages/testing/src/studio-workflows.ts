// The workflow builder's fixtures and handlers: the design's ticket router as a stored workflow (draft v8, v7
// current), validation that counts steps, CEL check and evaluation, step stats and runs, the canvas layout and
// the code endpoints. Use with studioHandlers (registry, schema, components).
import type { CelCheckOut, ComponentDetailOut, VersionOut, WorkflowValidationOut } from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { fakeCodegen } from "./studio";
import celContexts from "./fixtures/studio-cel-contexts.json";

const T = "2026-11-03T10:00:00Z";

export const ROUTE_BY_CATEGORY =
  'input.contains("refund") || input.contains("invoice") ? "Billing" : previous_step_content.contains("BUG") ? "Investigate" : "Draft & review"';

/** The design's ticket router, as the canvas builds it. */
export function ticketRouter(): Record<string, unknown> {
  return {
    id: "ticket-router",
    name: "ticket-router",
    steps: [
      { type: "Step", name: "Classify ticket", agent_id: "support-triage" },
      {
        type: "Router",
        name: "Route by category",
        selector: ROUTE_BY_CATEGORY,
        selector_type: "cel",
        choices: [
          { type: "Step", name: "Billing", agent_id: "billing-agent" },
          {
            type: "Parallel",
            name: "Investigate",
            steps: [
              { type: "Step", name: "Search KB", agent_id: "kb-researcher" },
              { type: "Step", name: "Check status page", executor_ref: "check_status" },
            ],
          },
          {
            type: "Loop",
            name: "Draft & review",
            max_iterations: 3,
            end_condition: 'last_step_content.contains("APPROVED")',
            end_condition_type: "cel",
            steps: [
              { type: "Step", name: "Draft reply", agent_id: "support-triage" },
              { type: "Step", name: "Review tone", agent_id: "qa-reviewer" },
            ],
          },
        ],
      },
      {
        type: "Condition",
        name: "Needs a human?",
        evaluator: 'previous_step_content.contains("ESCALATE")',
        evaluator_type: "cel",
        steps: [{ type: "Step", name: "Escalate", team_id: "escalation-team" }],
        else_steps: [{ type: "Step", name: "Send reply", executor_ref: "send_reply" }],
      },
    ],
  };
}

function workflowVersion(overrides: Partial<VersionOut>): VersionOut {
  return {
    version: 1,
    stage: "draft",
    label: null,
    notes: null,
    created_at: T,
    saved_at: T,
    revision: "r1",
    config: null,
    links: [],
    current: false,
    based_on_version: null,
    author_name: "Dana Okafor",
    updated_by_name: "Dana Okafor",
    change_summary: null,
    eval_status: null,
    published_by_name: null,
    published_at: null,
    promoted_from: null,
    ...overrides,
  } as VersionOut;
}

export function workflowDetail(config: Record<string, unknown> = ticketRouter()): ComponentDetailOut {
  const current = workflowVersion({ version: 7, stage: "published", current: true, config, revision: "r7" });
  const draft = workflowVersion({ version: 8, stage: "draft", based_on_version: 7, config, revision: "r8" });
  return {
    component: {
      id: "ticket-router",
      kind: "workflow",
      name: "ticket-router",
      description: null,
      current_version: 7,
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

function countSteps(nodes: unknown): number {
  if (!Array.isArray(nodes)) return 0;
  let count = 0;
  for (const node of nodes as Record<string, unknown>[]) {
    count += 1 + countSteps(node.steps) + countSteps(node.else_steps) + countSteps(node.choices);
  }
  return count;
}

export function workflowValidation(config: Record<string, unknown>): WorkflowValidationOut {
  const count = countSteps(config.steps);
  const unnamed = (config.steps as Record<string, unknown>[] | undefined)?.findIndex(
    (node) =>
      node.type === "Step" && !node.agent_id && !node.team_id && !node.executor_ref && !node.workflow_id,
  );
  const problems =
    unnamed !== undefined && unnamed >= 0
      ? [
          {
            path: `steps[${String(unnamed)}]`,
            severity: "error" as const,
            code: "executor_missing",
            message: "Pick what this step runs: an agent, a team, a workflow or a function.",
          },
        ]
      : [];
  return {
    step_count: count,
    sentence: problems.length
      ? `${String(count)} steps · ${String(problems.length)} problem`
      : `${String(count)} steps · valid`,
    validation: {
      ok: problems.length === 0,
      summary: problems.length ? "1 problem to fix before publishing." : "Valid.",
      layers: [
        { id: "shape", label: "Shape", status: "ok", hint: null, diagnostics: [] },
        {
          id: "rules",
          label: "Studio rules",
          status: problems.length ? "failed" : "ok",
          hint: null,
          diagnostics: problems,
        },
      ],
    },
  };
}

export function celCheck(expression: string, context: string, choices: string[] | null): CelCheckOut {
  if (context === "router") {
    const results = [...expression.matchAll(/\? "([^"]+)"|: "([^"]+)"$/g)].map(
      (match) => match[1] ?? match[2] ?? "",
    );
    const exhaustive = choices ? results.every((result) => choices.includes(result)) : null;
    return {
      ok: exhaustive !== false,
      type: "string",
      summary: exhaustive
        ? "Returns string · every result matches a choice"
        : "`Refund` isn't a choice of this router",
      findings: [],
      results,
      exhaustive,
    };
  }
  return { ok: true, type: "bool", summary: "Returns bool", findings: [], results: null, exhaustive: null };
}

export type WorkflowCalls = {
  validations: Record<string, unknown>[];
  checks: Record<string, unknown>[];
  evaluations: Record<string, unknown>[];
  layouts: Record<string, unknown>[];
  parses: Record<string, unknown>[];
  transforms: Record<string, unknown>[];
};

export function workflowCalls(): WorkflowCalls {
  return { validations: [], checks: [], evaluations: [], layouts: [], parses: [], transforms: [] };
}

/** Handlers for the builder; put them before studioHandlers so ticket-router resolves here. */
export function workflowHandlers(calls: WorkflowCalls = workflowCalls(), detail = workflowDetail()) {
  const base = `${API}/instances/:instance/studio`;
  return [
    http.get(`${base}/components/ticket-router`, () => HttpResponse.json(detail)),
    http.post(`${base}/codegen`, async ({ request }) => {
      const body = (await request.json()) as { kind: string; config: Record<string, unknown> };
      const generated = fakeCodegen(body.kind, body.config, null);
      // The router as the design's code places it.
      return HttpResponse.json({
        ...generated,
        spans: { ...generated.spans, "steps[1]": { line: 3, col_start: 4, col_end: 9, end_line: 4 } },
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
    http.post(`${base}/workflows/validate`, async ({ request }) => {
      const body = (await request.json()) as { config: Record<string, unknown> };
      calls.validations.push(body);
      return HttpResponse.json(workflowValidation(body.config));
    }),
    http.get(`${API}/studio/cel/contexts`, () => HttpResponse.json(celContexts)),
    http.post(`${API}/studio/cel/check`, async ({ request }) => {
      const body = (await request.json()) as {
        expression: string;
        context: string;
        choices: string[] | null;
      };
      calls.checks.push(body);
      return HttpResponse.json(celCheck(body.expression, body.context, body.choices));
    }),
    http.post(`${base}/cel/evaluate`, async ({ request }) => {
      const body = (await request.json()) as { sample: Record<string, unknown> };
      calls.evaluations.push(body);
      const input = typeof body.sample.input === "string" ? body.sample.input : "";
      return HttpResponse.json({
        result: input.includes("refund") ? "Billing" : "Draft & review",
        type: "string",
        evaluator: "agno",
        error: null,
        span: null,
        note: null,
      });
    }),
    http.get(`${base}/components/:id/step-stats`, () =>
      HttpResponse.json({
        window: "7d",
        traces_scanned: 12,
        sampled: false,
        steps: [{ name: "Classify ticket", avg_ms: 1100, count: 12, errors: 0 }],
      }),
    ),
    http.get(`${base}/components/:id/step-runs`, ({ request }) => {
      const step = new URL(request.url).searchParams.get("step");
      return HttpResponse.json(
        step === "Classify ticket"
          ? [
              {
                run_id: "run_w1",
                session_id: "ses_w1",
                created_at: 1,
                status: "COMPLETED",
                content: "Category: BILLING",
                success: true,
                error: null,
              },
            ]
          : [],
      );
    }),
    http.get(`${base}/components/:id/canvas-layout`, () =>
      HttpResponse.json({ version: 8, layout: {}, updated_at: null }),
    ),
    http.put(`${base}/components/:id/canvas-layout`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.layouts.push(body);
      return HttpResponse.json({ ...body, updated_at: T });
    }),
    http.post(`${base}/parse`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.parses.push(body);
      return HttpResponse.json({
        ok: true,
        config: detail.draft?.config ?? {},
        variable: "ticket_router",
        diagnostics: [],
        spans: {},
        code_owned: [],
        ruff: { available: true, status: "ruff · 0 errors", formatted: false, messages: [] },
      });
    }),
    http.post(`${base}/transform`, async ({ request }) => {
      const body = (await request.json()) as { code: string; config: Record<string, unknown> };
      calls.transforms.push(body);
      return HttpResponse.json({
        code: `${body.code}# edited\n`,
        config: body.config,
        equivalent: true,
        changed: [],
        diagnostics: [],
        spans: {},
        code_owned: [],
        ruff: { available: true, status: "ruff · 0 errors", formatted: false, messages: [] },
      });
    }),
  ];
}
