// Ask your OS against stubbed APIs: with AI features off nothing mentions it outside settings; with them on, the
// Home box takes the suggestion with Tab, streams an answer with tool chips and sources, and a source opens the
// trace; the command palette hands what was typed to the Ask page.
import { expect, test, type Page } from "@playwright/test";

import { T, stubApi } from "./stubs";

const ANSWER =
  "daily-brief failed because `web_search` timed out twice (30 s each) in *Gather news*, so it never reached *Write brief*.";

function sse(events: Record<string, unknown>[]): string {
  return events
    .map(
      (event, index) =>
        `id: ${String(index + 1)}\nevent: ${String(event.event)}\ndata: ${JSON.stringify(event)}\n\n`,
    )
    .join("");
}

const stream = [
  { event: "answer.started", model: "ollama:qwen3:8b" },
  { event: "answer.tool_started", id: "c1", name: "get_schedule_runs" },
  { event: "answer.tool_completed", id: "c1", name: "get_schedule_runs", status: "done", duration_ms: 120 },
  { event: "answer.tool_started", id: "c2", name: "get_trace" },
  { event: "answer.tool_completed", id: "c2", name: "get_trace", status: "done", duration_ms: 340 },
  { event: "answer.content", delta: ANSWER },
  {
    event: "answer.sources",
    sources: [
      { kind: "schedule", label: "Schedule daily-brief", path: "/i/prod-agentos/scheduler?schedule=sch_1" },
      { kind: "trace", label: "Trace daily-brief · 9c1e7d40", path: "/i/prod-agentos/traces/tr_9c1e7d40" },
    ],
  },
  { event: "answer.completed", content: ANSWER, model: "ollama:qwen3:8b" },
];

async function stubAssistant(page: Page) {
  await page.route(/\/api\/v1\/system\/features$/, (route) =>
    route.fulfill({
      json: { features: { assistant: true, "assistant.summaries": true, "assistant.suggestions": true } },
    }),
  );
  await page.route(/\/api\/v1\/assistant\/status$/, (route) =>
    route.fulfill({
      json: {
        features: { assistant: true, summaries: true, suggestions: true },
        can_use: true,
        provider: "ollama",
        data_notice: "Answers are generated on our own Ollama server.",
        budget: { month: "2026-11", org_tokens: 0, org_limit: null, user_tokens: 0, user_limit: null },
        requests_per_minute: 10,
      },
    }),
  );
  await page.route(/\/assistant\/questions$/, (route) =>
    route.fulfill({ status: 202, json: { message_id: "msg_1", conversation_id: "conv_1", reused: false } }),
  );
  await page.route(/\/assistant\/messages\/msg_1\/events$/, (route) =>
    route.fulfill({ contentType: "text/event-stream", body: sse(stream) }),
  );
  await page.route(/\/assistant\/conversations$/, (route) =>
    route.fulfill({
      json: [{ id: "conv_1", title: "Why did daily-brief fail last night?", created_at: T, updated_at: T }],
    }),
  );
}

async function stubOverview(page: Page) {
  await page.route(/\/api\/v1\/instances\/[^/]+\/overview/, (route) =>
    route.fulfill({
      json: {
        instance_id: "ins_01M6A0EEZEQ373S26F2014PRD",
        range: "7d",
        start: T,
        end: T,
        generated_at: T,
        cached: false,
        sampled: false,
        counts: { agents: 6, teams: 3, workflows: 5 },
        kpis: null,
        runs_per_day: null,
        model_usage: null,
        primitives: null,
        pending_approvals: null,
        attention: [
          {
            key: "schedule:sch_1",
            kind: "schedule_failing",
            severity: "danger",
            title: "daily-brief failed twice",
            detail: "Timeout in web_search after 30 s",
            action: null,
          },
        ],
        activity: [],
        unavailable: {},
      },
    }),
  );
}

test("with AI features off, nothing mentions Ask your OS", async ({ page }) => {
  await stubApi(page);
  await page.goto("/i/prod-agentos/home");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Ask your OS")).toHaveCount(0);
  await page.keyboard.press("Control+k");
  await page.getByPlaceholder("Search or jump to…").fill("ask");
  await expect(page.getByRole("option", { name: /Ask your OS/ })).toHaveCount(0);
});

test("Home: Tab takes the suggestion, the answer streams with chips and sources, a source opens the trace", async ({
  page,
}) => {
  await stubApi(page);
  await stubOverview(page);
  await stubAssistant(page);
  await page.route(/\/os\/traces\/tr_9c1e7d40/, (route) =>
    route.fulfill({ status: 404, json: { detail: "x" } }),
  );
  await page.goto("/i/prod-agentos/home");

  const box = page.getByLabel("Ask your OS", { exact: true });
  await expect(box).toHaveAttribute("placeholder", "Why did daily-brief fail last night?");
  await box.fill("Why did d");
  await box.press("Tab");
  await expect(box).toHaveValue("Why did daily-brief fail last night?");
  await expect(page.getByText(/Answers are generated on our own Ollama server/)).toBeVisible();
  await page.getByRole("button", { name: "Send" }).click();

  const answer = page.getByRole("article", { name: "Answer from Ask your OS" });
  await expect(answer.getByText(/never reached/)).toBeVisible();
  await expect(answer.getByText("get_schedule_runs")).toBeVisible();
  await expect(answer.getByText("get_trace")).toBeVisible();
  await expect(answer.getByText(/Generated by ollama:qwen3:8b/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Ask your OS" })).toBeVisible();

  await answer.getByRole("link", { name: "Trace daily-brief · 9c1e7d40" }).click();
  await expect(page).toHaveURL(/\/i\/prod-agentos\/traces\/tr_9c1e7d40$/);
});

test("the command palette hands the typed question to the Ask page", async ({ page }) => {
  await stubApi(page);
  await stubAssistant(page);
  await page.route(/\/api\/v1\/search/, (route) => route.fulfill({ json: { data: [] } }));
  await page.goto("/i/prod-agentos/home");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.keyboard.press("Control+k");
  await page.getByPlaceholder("Search or jump to…").fill("which runs failed today");
  await page.getByRole("option", { name: /Ask your OS: which runs failed today/ }).click();
  await expect(page).toHaveURL(/\/i\/prod-agentos\/ask\?q=which/);
  await expect(page.getByLabel("Ask your OS", { exact: true })).toHaveValue("which runs failed today");
});
