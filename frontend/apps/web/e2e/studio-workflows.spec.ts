// The workflow builder against stubbed Studio routes: the design's ticket router on the canvas, a step inserted from
// a connection, a draft test run in the Playground lighting steps up as its events stream in, the code view following
// the selection, and a 200-step workflow that pans and zooms within the frame budget.
import { expect, test, type Page } from "@playwright/test";

import celContexts from "../../../packages/testing/src/fixtures/studio-cel-contexts.json" with { type: "json" };
import workflowSchema from "../../../packages/testing/src/fixtures/studio-schema-workflow.json" with { type: "json" };
import { T, stubApi } from "./stubs";

const STUDIO = /\/api\/v1\/instances\/[^/]+\/studio\//;
const SELECTOR =
  'input.contains("refund") || input.contains("invoice") ? "Billing" : previous_step_content.contains("BUG") ? "Investigate" : "Draft & review"';

function ticketRouter(): Record<string, unknown> {
  return {
    id: "ticket-router",
    name: "ticket-router",
    steps: [
      { type: "Step", name: "Classify ticket", agent_id: "support-triage" },
      {
        type: "Router",
        name: "Route by category",
        selector: SELECTOR,
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

/** 200 nodes: Routers with a step and a Parallel of one step as choices. */
function twoHundred(): Record<string, unknown> {
  return {
    id: "ticket-router",
    name: "ticket-router",
    steps: Array.from({ length: 50 }, (_, index) => ({
      type: "Router",
      name: `Route ${String(index)}`,
      selector: '"A"',
      selector_type: "cel",
      choices: [
        { type: "Step", name: `A ${String(index)}`, agent_id: "support-triage" },
        {
          type: "Parallel",
          name: `P ${String(index)}`,
          steps: [{ type: "Step", name: `B ${String(index)}`, agent_id: "kb-researcher" }],
        },
      ],
    })),
  };
}

function version(number: number, stage: string, config: Record<string, unknown>) {
  return {
    version: number,
    stage,
    label: null,
    notes: null,
    created_at: T,
    saved_at: T,
    revision: `r${String(number)}`,
    config,
    links: [],
    current: stage === "published",
    based_on_version: stage === "draft" ? number - 1 : null,
    author_name: "Daniel Okafor",
    updated_by_name: "Daniel Okafor",
    change_summary: null,
    eval_status: null,
    published_by_name: null,
    published_at: null,
    promoted_from: null,
  };
}

function sse(events: Record<string, unknown>[]): string {
  return events.map((event) => `event: ${String(event.event)}\ndata: ${JSON.stringify(event)}\n\n`).join("");
}

const RUN = { run_id: "run_w1", session_id: "ses_w1", workflow_id: "ticket-router" };
const RUN_EVENTS = [
  { event: "WorkflowStarted", ...RUN },
  { event: "StepStarted", ...RUN, step_name: "Classify ticket", step_index: 0 },
  { event: "StepCompleted", ...RUN, step_name: "Classify ticket", step_index: 0, content: "BILLING" },
  { event: "RouterExecutionStarted", ...RUN, step_name: "Route by category", step_index: 1 },
  { event: "StepStarted", ...RUN, step_name: "Billing", step_index: 0 },
];

async function stubStudio(page: Page, config: Record<string, unknown>) {
  const detail = {
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
    versions: [],
    draft: version(8, "draft", config),
    current: version(7, "published", config),
    owner_group_id: null,
    labels: [],
  };
  const registry = {
    instance: "staging-agentos",
    entries: [],
    counts: {},
    total: 0,
    bridge: false,
  };
  await page.route(/\/api\/v1\/studio\/schema\/workflow$/, (route) =>
    route.fulfill({ json: workflowSchema }),
  );
  await page.route(/\/api\/v1\/studio\/cel\/contexts$/, (route) => route.fulfill({ json: celContexts }));
  await page.route(/\/api\/v1\/studio\/cel\/check$/, (route) =>
    route.fulfill({
      json: {
        ok: true,
        type: "string",
        summary: "Returns string · every result matches a choice",
        findings: [],
        results: ["Billing", "Investigate", "Draft & review"],
        exhaustive: true,
      },
    }),
  );
  await page.route(STUDIO, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^.*\/studio/, "");
    const method = route.request().method();
    if (path === "/registry") return route.fulfill({ json: registry });
    if (path === "/components") return route.fulfill({ json: [] });
    if (path === "/components/ticket-router") return route.fulfill({ json: detail });
    if (path.endsWith("/code")) {
      return route.fulfill({
        json: { code_backed: false, code: null, stale: false, updated_by_name: null, updated_at: null },
      });
    }
    if (path.endsWith("/canvas-layout")) {
      return route.fulfill({ json: { version: 8, layout: {}, updated_at: null } });
    }
    if (path.endsWith("/step-stats")) {
      return route.fulfill({ json: { window: "7d", traces_scanned: 0, sampled: false, steps: [] } });
    }
    if (path.endsWith("/step-runs")) return route.fulfill({ json: [] });
    if (path.endsWith("/diff"))
      return route.fulfill({ status: 404, json: { title: "No diff", status: 404 } });
    if (path === "/workflows/validate") {
      return route.fulfill({
        json: {
          step_count: 12,
          sentence: "12 steps · valid",
          validation: { ok: true, summary: "Valid.", layers: [] },
        },
      });
    }
    if (path === "/codegen") {
      const code =
        'from agno.workflow import Router, Step, Workflow\n\nticket_router = Workflow(\n    id="ticket-router",\n    steps=[\n        Router(\n            name="Route by category",\n        ),\n    ],\n)\n';
      return route.fulfill({
        json: {
          code,
          filename: "workflows/ticket_router.py",
          spans: { "steps[1]": { line: 6, col_start: 8, col_end: 15, end_line: 8 } },
          marks: {},
          notes: [],
          ruff: { available: true, status: "ruff · 0 errors", formatted: false, messages: [] },
          base_code: null,
        },
      });
    }
    if (path.startsWith("/components/ticket-router/configs/") && method === "PATCH") {
      const body = route.request().postDataJSON() as { config: Record<string, unknown> };
      return route.fulfill({ json: { ...detail.draft, config: body.config, revision: "r9" } });
    }
    if (path.endsWith("/test-runs")) {
      return route.fulfill({ contentType: "text/event-stream", body: sse(RUN_EVENTS) });
    }
    return route.fulfill({ status: 404, json: { title: "Not stubbed", status: 404, detail: path } });
  });
}

const canvas = (page: Page) => page.getByRole("application", { name: "Workflow canvas" });

test.describe("workflow builder", () => {
  test("draws the ticket router, inserts a step and lights steps up during a test run", async ({ page }) => {
    await stubApi(page);
    await stubStudio(page, ticketRouter());
    await page.goto("/i/staging-agentos/studio/workflows/ticket-router");

    const board = canvas(page);
    await expect(board.getByRole("button", { name: /^Step Classify ticket/ })).toBeVisible();
    await expect(board.getByRole("button", { name: /^Router Route by category/ })).toBeVisible();
    await expect(board.getByText("Draft & review").first()).toBeVisible();
    await expect(page.getByText("12 steps · valid")).toBeVisible();

    await board.getByRole("button", { name: "Insert step here" }).first().click();
    const inserted = board.getByRole("button", { name: "Step Step", exact: true });
    await expect(inserted).toBeVisible();
    await expect(inserted).toHaveAccessibleDescription(/^no executor yet/);
    await page.getByRole("button", { name: "Undo" }).click();
    await expect(board.getByRole("button", { name: "Step Step", exact: true })).toHaveCount(0);

    await page.getByRole("button", { name: "Playground" }).click();
    const panel = page.getByRole("complementary", { name: "Playground" });
    await panel.getByRole("textbox", { name: "Test message" }).fill("I was charged twice, need a refund");
    // The Playground takes the inspector's place: fit the view to what's left so the router's choices show.
    await page.getByRole("button", { name: "Auto-layout" }).click();
    await panel.getByRole("button", { name: "Run", exact: true }).click();
    await expect(board.locator('[data-path="steps[0]"] [data-slot="node-card"]')).toHaveAttribute(
      "data-status",
      "done",
    );
    await expect(board.locator('[data-path="steps[1].choices[0]"] [data-slot="node-card"]')).toHaveAttribute(
      "data-status",
      "running",
    );
  });

  test("the code view highlights the selected router", async ({ page }) => {
    await stubApi(page);
    await stubStudio(page, ticketRouter());
    await page.goto("/i/staging-agentos/studio/workflows/ticket-router");
    await canvas(page)
      .getByRole("button", { name: /^Router Route by category/ })
      .click();
    await expect(page).toHaveURL(/node=steps%5B1%5D/);
    await page.getByRole("radio", { name: "Code" }).click();
    const code = page.getByRole("textbox", { name: "Generated workflows/ticket_router.py" });
    await expect(code.locator(".cm-focus-line")).toHaveCount(3);
    await expect(page.getByRole("complementary", { name: "Step properties" })).toContainText(
      "Route by category",
    );
  });

  test("a 200-step workflow pans and zooms within the frame budget", async ({ page }) => {
    await stubApi(page);
    await stubStudio(page, twoHundred());
    await page.goto("/i/staging-agentos/studio/workflows/ticket-router");
    const board = canvas(page);
    await expect(board.getByRole("button", { name: /^Router Route 0/ })).toBeVisible({ timeout: 15_000 });
    const box = await board.boundingBox();
    if (!box) throw new Error("no canvas");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);

    // Frame intervals while the canvas pans (wheel) and zooms (ctrl + wheel).
    await page.evaluate(() => {
      const scope = window as unknown as { frames_: number[] };
      scope.frames_ = [];
      let last = performance.now();
      const tick = (now: number) => {
        scope.frames_.push(now - last);
        last = now;
        if (scope.frames_.length < 240) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
    for (let step = 0; step < 60; step += 1) {
      await page.mouse.wheel(0, step % 2 === 0 ? 120 : -60);
    }
    await page.keyboard.down("Control");
    for (let step = 0; step < 20; step += 1) await page.mouse.wheel(0, step < 10 ? -100 : 100);
    await page.keyboard.up("Control");
    const frames = await page.evaluate(() => (window as unknown as { frames_: number[] }).frames_.slice(5));
    frames.sort((a, b) => a - b);
    const median = frames[Math.floor(frames.length / 2)] ?? 0;
    expect(median).toBeLessThanOrEqual(1000 / 60 + 1);
  });
});
