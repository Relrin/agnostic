// Coding agents against stubbed APIs: repo-coder (Pi in a Docker sandbox) shows its badge in chat, its run draws the
// file it wrote, the edit and the failing shell command as cards and leaves the report as an artefact from the
// sandbox; in Studio the coding agent template opens with the coding-agent section.
import { expect, test, type Page, type Route } from "@playwright/test";

import piRun from "../../../packages/testing/src/fixtures/coding-run-pi.json" with { type: "json" };
import agentSchema from "../../../packages/testing/src/fixtures/studio-schema-agent.json" with { type: "json" };
import { T, stubApi } from "./stubs";

const GATEWAY = /\/api\/v1\/instances\/[^/]+\/os\//;
const SESSION = "ses_code_1";
const RUN_ID = "run_code_1";
const SANDBOX = {
  provider: "docker",
  image: "agnostic-coding:0.1.0",
  network: "isolated",
  cpus: 2,
  memory_mb: 2048,
  turn_timeout_s: 900,
};
const CODING_AGENTS = {
  items: [
    {
      id: "repo-coder",
      name: "Repo coder",
      harness: "pi",
      source: "code",
      version: null,
      model: { id: "mock-coder", provider: "Agnostic" },
      sandbox: SANDBOX,
      tools: ["bash", "read", "write", "edit"],
    },
  ],
};
const CAPABILITIES = {
  bridge_version: "0.3.0",
  api_version: "v1",
  endpoints: ["GET /agnostic/v1/capabilities", "GET /agnostic/v1/coding-agents"],
  features: { coding_agents: { enabled: true } },
};
const REPORT =
  "# Support volume\n\n| Quarter | Tickets |\n|---|---|\n| Q1 | 61 |\n| Q2 | 82 |\n| Q3 | 97 |\n";
const ARTIFACT = {
  id: "art_code_report",
  storage_key: `${SESSION}/art_report.md`,
  session_id: SESSION,
  run_id: RUN_ID,
  component_kind: "agent",
  component_id: "repo-coder",
  kind: "file",
  filename: "report.md",
  title: "report.md",
  content_type: "text/markdown",
  size: REPORT.length,
  sha256: "0".repeat(64),
  path: "outputs/report.md",
  source: "docker",
  producer: null,
  revision: 1,
  role: "output",
  created_at: T,
};

function sse(events: Record<string, unknown>[]): string {
  return events.map((event) => `event: ${String(event.event)}\ndata: ${JSON.stringify(event)}\n\n`).join("");
}

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });

/** The runtime's gateway: the bridge's coding routes, repo-coder's sessions and runs, and its artefacts. */
async function stubCodingGateway(page: Page) {
  const state = { ran: false };
  await page.route(GATEWAY, (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^.*\/os\//, "");
    const method = route.request().method();
    const session = {
      session_id: SESSION,
      session_name: "Support volume report",
      session_state: {},
      user_id: "usr_dana",
      agent_id: "repo-coder",
      created_at: T,
      updated_at: T,
    };
    if (method === "GET" && path === "agnostic/v1/capabilities") return json(route, CAPABILITIES);
    if (method === "GET" && path === "agnostic/v1/coding-agents") return json(route, CODING_AGENTS);
    if (method === "GET" && path === "agents")
      return json(route, [
        { id: "support-triage", name: "Support triage", current_version: 3 },
        { id: "repo-coder", name: "Repo coder", metadata: { sdk: "pi" } },
      ]);
    if (method === "GET" && (path === "teams" || path === "workflows")) return json(route, []);
    if (method === "GET" && path === "sessions") {
      const items = state.ran ? [session] : [];
      return json(route, {
        data: items,
        meta: { page: 1, limit: 20, total_pages: 1, total_count: items.length },
      });
    }
    if (method === "GET" && path === `sessions/${SESSION}`)
      return json(route, { ...session, session_summary: null });
    if (method === "GET" && path === `sessions/${SESSION}/runs`)
      return json(
        route,
        state.ran
          ? [
              {
                run_id: RUN_ID,
                agent_id: "repo-coder",
                status: "COMPLETED",
                run_input: "Write the support volume report",
                events: piRun,
                created_at: T,
              },
            ]
          : [],
      );
    if (method === "POST" && path === "agents/repo-coder/runs") {
      state.ran = true;
      return route.fulfill({ contentType: "text/event-stream", body: sse(piRun) });
    }
    if (method === "GET" && path === "agnostic/v1/artifacts")
      return json(route, { data: state.ran ? [ARTIFACT] : [], scanned_sessions: 1 });
    if (method === "POST" && path === "agnostic/v1/artifacts/sync")
      return json(route, { session_id: SESSION, runs_synced: 1, artifacts: 1 });
    if (method === "GET" && path === "approvals")
      return json(route, { data: [], meta: { page: 1, limit: 20, total_pages: 1, total_count: 0 } });
    return json(route, { detail: `Not stubbed: ${method} ${path}` }, 404);
  });
  await page.route(/\/api\/v1\/instances\/[^/]+\/artifacts\/[^/]+\/content\//, (route) =>
    route.fulfill({ contentType: "text/markdown", body: REPORT }),
  );
  return state;
}

test("chat: a coding agent's run shows its harness, its tool calls as cards and the report it left", async ({
  page,
}) => {
  await stubApi(page);
  await stubCodingGateway(page);
  await page.goto("/i/prod-agentos/chat/agents/repo-coder");

  const badge = page.getByRole("button", { name: "Coding agent: Pi on Docker" });
  await expect(badge).toBeVisible();
  await badge.hover();
  await expect(page.getByRole("tooltip")).toContainText("Image agnostic-coding:0.1.0");

  await page.getByRole("textbox", { name: "Message Repo coder" }).fill("Write the support volume report");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/chat/agents/repo-coder/${SESSION}`));

  const run = page.getByRole("article", { name: `Run ${RUN_ID}` });
  const calls = run.getByRole("list", { name: "Tool calls" });
  await expect(calls.getByRole("group", { name: "write: outputs/report.md" })).toBeVisible();
  await expect(calls.getByLabel("Diff of outputs/report.md")).toContainText("| Q3 | 97 |");
  const bash = calls.getByRole("group", { name: /^bash: wc -l outputs\/report\.md/ });
  await expect(bash.getByText("exit 1")).toBeVisible();
  await expect(bash.getByLabel("Output")).toContainText("No such file or directory");
  await expect(run.getByText("I wrote the report to outputs/report.md and added Q3.")).toBeVisible();

  await run.getByRole("button", { name: "Open report.md" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByText("from Docker sandbox")).toBeVisible();
});

const TEMPLATE_CONFIG = {
  name: "Repo coder 2",
  instructions: ["Work in the current directory; it is a fresh sandbox for this session."],
  model: { id: "mock-coder", provider: "Agnostic" },
  metadata: { agnostic: { coding_agent: { harness: "pi" } } },
};

function studioComponent(id: string, source: "studio" | "code") {
  return {
    id,
    kind: "agent",
    name: id,
    description: null,
    current_version: null,
    source,
    created_at: T,
    updated_at: T,
    deleted_at: null,
  };
}

const DRAFT = {
  version: 1,
  stage: "draft",
  tag: "v1 draft",
  current: false,
  label: null,
  notes: null,
  created_at: T,
  updated_at: T,
  revision: "r1",
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
  config: TEMPLATE_CONFIG,
};

async function stubCodingStudio(page: Page) {
  await page.route(/\/api\/v1\/studio\/schema\/agent$/, (route) => json(route, agentSchema));
  await page.route(/\/api\/v1\/studio\/templates(\?.*)?$/, (route) =>
    json(route, [
      { id: "blank-agent", kind: "agent", label: "Blank agent", description: "A model and nothing else." },
      {
        id: "coding-agent",
        kind: "agent",
        label: "Coding agent",
        description: "Pi in a Docker sandbox; files written to outputs/ become artefacts.",
      },
    ]),
  );
  await page.route(/\/api\/v1\/instances\/[^/]+\/studio\//, (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^.*\/studio/, "");
    const method = route.request().method();
    if (path === "/sources/conflicts/count" || path.endsWith("/source")) return route.fallback();
    if (method === "GET" && path === "/components")
      return json(route, [
        {
          component: studioComponent("repo-coder", "code"),
          draft_updated_at: null,
          draft_version: null,
          editable: false,
          labels: [],
          latest_version: null,
          owner_group_id: null,
          runs_7d: null,
        },
      ]);
    if (method === "GET" && path === "/registry")
      return json(route, { instance: "staging-agentos", entries: [], counts: {}, total: 0, bridge: true });
    if (method === "POST" && path === "/components") {
      const body = route.request().postDataJSON() as { template_id?: string };
      expect(body.template_id).toBe("coding-agent");
      return json(route, { component: studioComponent("repo-coder-2", "studio"), draft: DRAFT }, 201);
    }
    if (method === "GET" && path === "/components/repo-coder-2")
      return json(route, {
        component: studioComponent("repo-coder-2", "studio"),
        editable: true,
        versions: [{ ...DRAFT, config: null }],
        draft: DRAFT,
        current: null,
        owner_group_id: null,
        labels: [],
      });
    if (method === "GET" && path.endsWith("/code"))
      return json(route, {
        code_backed: false,
        code: null,
        stale: false,
        updated_by_name: null,
        updated_at: null,
      });
    if (method === "POST" && path === "/codegen")
      return json(route, {
        code: "from agno.agent import Agent\n",
        filename: "agents/repo_coder_2.py",
        spans: {},
        marks: {},
        notes: [],
        ruff: { available: true, status: "ruff · 0 errors", formatted: false, messages: [] },
        base_code: null,
      });
    if (method === "PATCH" && path.startsWith("/components/repo-coder-2/configs/")) {
      const body = route.request().postDataJSON() as { config: Record<string, unknown> };
      return json(route, { ...DRAFT, config: body.config, revision: "r2" });
    }
    return json(route, { type: "x", title: "Not stubbed", status: 404, detail: `${method} ${path}` }, 404);
  });
}

test("studio: the coding agent template opens with the coding-agent section", async ({ page }) => {
  await stubApi(page);
  await stubCodingGateway(page);
  await stubCodingStudio(page);
  await page.goto("/i/staging-agentos/studio/agents");

  const table = page.getByRole("table", { name: "Agents" });
  await expect(table.getByRole("button", { name: "Coding agent: Pi on Docker" })).toBeVisible();

  await page.getByRole("button", { name: "New agent" }).click();
  const dialog = page.getByRole("dialog", { name: "New agent" });
  await dialog.getByLabel("Name").fill("Repo coder 2");
  await dialog.getByText("Template", { exact: true }).click();
  await dialog.getByRole("combobox", { name: "Template" }).click();
  await page.getByRole("option", { name: /^Coding agent/ }).click();
  await dialog.getByRole("button", { name: "Create agent" }).click();

  await expect(page).toHaveURL(/\/studio\/agents\/repo-coder-2/);
  const section = page.getByLabel("Coding agent settings");
  await expect(section).toBeVisible();
  await expect(section.getByText("Test runs use the published version")).toBeVisible();
  await expect(section.getByLabel("CPUs")).toHaveAttribute("placeholder", "2");
  await expect(section.getByLabel("Image")).toHaveAttribute("placeholder", "agnostic-coding:0.1.0");
});
