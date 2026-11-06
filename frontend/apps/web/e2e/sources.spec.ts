// Code sources against stubbed APIs: the sidebar's conflict dot, the GitHub source's incoming changes with what
// pulling does, the outgoing change with its branch and review requirement, a conflict resolved by keeping the
// repository's value, a connection edited (only what changed is sent) and verified, and a source disconnected.
import { expect, test, type Page } from "@playwright/test";

import { access, instances, stubApi } from "./stubs";

const SOURCES = /\/api\/v1\/instances\/[^/]+\/studio\/sources/;
const CONNECTIONS = /\/api\/v1\/studio\/connections/;
const policy = {
  pull_mode: "on_demand",
  publish_mode: "open_pr",
  branch_template: "studio/{component}-v{version}",
  commit_template: "{component}: {summary}",
  block_publish_until_merged: false,
};
const github = {
  id: "src_github",
  instance_id: instances[1]?.id,
  provider: "github",
  provider_label: "GitHub",
  repo: "northwind/agent-platform",
  branch: "main",
  local_path: null,
  connection_id: "scn_github",
  connection_name: "Northwind GitHub",
  auth: "GitHub App · read & write",
  status: "active",
  status_detail: null,
  head_sha: "a41c9e2a0c1f4b0e9d6a2b3c4d5e6f708192a3b4",
  last_fetched_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
  mappings: [
    { glob: "agents/*.py", target_kind: "agents", writable: true, count: 6 },
    { glob: "registry.py", target_kind: "registry", writable: false, count: 1 },
  ],
  policy,
  convention: null,
  incoming: 1,
  outgoing: 1,
  conflicts: 1,
  open_pull_requests: 0,
  webhook: true,
  version: 2,
};
const incoming = {
  id: "sch_in",
  direction: "incoming",
  path: "workflows/ticket_router.py",
  component_kind: "workflow",
  component_id: "ticket-router",
  commit_sha: "7c2e1f0aa11b22c33d44e55f66a77b88c99d00e1",
  author_name: "Sam Rivera",
  committed_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
  message: "Route outage tickets to on-call",
  additions: 6,
  deletions: 2,
  outcome: { action: "new_draft", version: 9, beside_version: 8 },
  outcome_sentence: "Becomes draft v9 of ticket-router, next to your draft v8",
  summary: null,
  draft_version: 8,
  diagnostics: [],
  included: true,
  status: "pending",
  result_version: null,
};
const outgoing = {
  ...incoming,
  id: "sch_out",
  direction: "outgoing",
  path: "agents/support_triage.py",
  component_kind: "agent",
  component_id: "support-triage",
  commit_sha: null,
  author_name: "Priya Nair",
  message: null,
  additions: 2,
  deletions: 1,
  outcome: { action: "edit", stage: "draft" },
  outcome_sentence: null,
  summary: "temperature 0.7 → 0.2, one new instruction",
  draft_version: 4,
};
const conflict = {
  id: "scf_1",
  change_id: "sch_c",
  path: "agents/billing_agent.py",
  component_id: "billing-agent",
  field_path: "instructions[2]",
  base_value: "Refunds over $100 need a manager.",
  repo: {
    value: "Refunds over $200 need a manager.",
    present: true,
    author: "Sam Rivera",
    reference: "e81f0c4",
  },
  studio: {
    value: "Refunds over $150 need a manager.",
    present: true,
    author: "Maya Chen",
    reference: "draft v6",
  },
  status: "open",
  resolution: null,
  resolved_by_name: null,
};

const connection = {
  id: "scn_github",
  name: "Northwind GitHub",
  provider: "github",
  provider_label: "GitHub",
  auth_kind: "token",
  access: "read_write",
  api_url: null,
  web_url: null,
  app_slug: null,
  installation_id: null,
  account: "agnostic-bot",
  status: "verified",
  last_error: null,
  last_checked_at: new Date(Date.now() - 3600 * 1000).toISOString(),
  version: 3,
};

/** The org's connections: every PATCH body and verify are kept. */
async function stubConnections(page: Page) {
  const seen = { patches: [] as Record<string, unknown>[], verified: 0 };
  await page.route(CONNECTIONS, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname === "/api/v1/studio/connections" && method === "GET") {
      return route.fulfill({ json: [connection] });
    }
    if (url.pathname === "/api/v1/studio/connections/scn_github" && method === "PATCH") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      seen.patches.push(body);
      return route.fulfill({ json: { ...connection, ...body, version: 4 } });
    }
    if (url.pathname === "/api/v1/studio/connections/scn_github/verify" && method === "POST") {
      seen.verified += 1;
      return route.fulfill({ json: connection });
    }
    return route.fulfill({ status: 404, json: { title: "Not stubbed", status: 404 } });
  });
  return seen;
}

test("sources: the conflict dot, the changes and a conflict kept from the repository", async ({ page }) => {
  await stubApi(page);
  await stubConnections(page);
  const resolved: string[] = [];
  await page.route(SOURCES, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api\/v1\/instances\/[^/]+\/studio\/sources/, "");
    const method = route.request().method();
    if (path === "/conflicts/count") {
      return route.fulfill({ json: { instance_id: instances[1]?.id, count: resolved.length ? 0 : 1 } });
    }
    if (path === "" && method === "GET") return route.fulfill({ json: [github] });
    if (path === "/src_github/changes") {
      return route.fulfill({
        json: {
          remote: {
            ref: "origin/main",
            head_sha: "9f03b77c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f60",
            fetched_at: null,
          },
          incoming: [incoming],
          outgoing: [outgoing],
          conflicts: resolved.length ? [] : [conflict],
          pull_requests: [],
        },
      });
    }
    if (path === "/src_github/commit-preview") {
      return route.fulfill({
        json: {
          branch: "studio/support-triage-v4",
          base_branch: "main",
          mode: "open_pr",
          message: "support-triage: lower temperature, add refund rule",
          review_requirement: "1 review from Platform required",
          sentence: "Branch studio/support-triage-v4 · PR into main · 1 review from Platform required",
        },
      });
    }
    if (path === "/src_github/conflicts/scf_1/resolve" && method === "POST") {
      resolved.push((route.request().postDataJSON() as { resolution: string }).resolution);
      return route.fulfill({ json: { ...conflict, status: "resolved", resolution: "keep_repo" } });
    }
    return route.fulfill({
      status: 404,
      json: { title: "Not stubbed", status: 404, detail: `${method} ${path}` },
    });
  });

  await page.goto("/i/staging-agentos/studio/sources");
  await expect(page.getByRole("heading", { name: "Code sources" })).toBeVisible();
  await expect(page.getByRole("img", { name: "1 conflict" })).toBeVisible();

  const card = page.getByRole("list", { name: "Connected sources" }).getByRole("button");
  await expect(card).toHaveAttribute("aria-pressed", "true");
  await expect(card).toContainText("↓ 1 incoming");
  await expect(page.getByText("Becomes draft v9 of ticket-router, next to your draft v8")).toBeVisible();
  await expect(
    page.getByText("Branch studio/support-triage-v4 · PR into main · 1 review from Platform required"),
  ).toBeVisible();

  const article = page.getByRole("article", { name: "Conflict on instructions[2]" });
  await expect(article).toContainText("Refunds over $200 need a manager.");
  await article.getByRole("button", { name: "Keep repo" }).click();
  await expect(article).toBeHidden();
  expect(resolved).toEqual(["keep_repo"]);
});

test("sources: a connection edited for GitHub Enterprise and verified, and a source disconnected", async ({
  page,
}) => {
  await stubApi(page);
  // Someone who manages sources (the shared stub's owner has no studio scopes).
  const manager = {
    ...access,
    control_plane_scopes: [...access.control_plane_scopes, "studio:sources:write", "studio:sources:delete"],
  };
  await page.route(/\/api\/v1\/me\/access/, (route) => route.fulfill({ json: manager }));
  const seen = await stubConnections(page);
  const deleted: string[] = [];
  await page.route(SOURCES, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api\/v1\/instances\/[^/]+\/studio\/sources/, "");
    const method = route.request().method();
    if (path === "/conflicts/count")
      return route.fulfill({ json: { instance_id: instances[1]?.id, count: 0 } });
    if (path === "" && method === "GET") return route.fulfill({ json: deleted.length ? [] : [github] });
    if (path === "/src_github/changes") {
      return route.fulfill({
        json: {
          remote: { ref: "origin/main", head_sha: null, fetched_at: null },
          incoming: [],
          outgoing: [],
          conflicts: [],
          pull_requests: [],
        },
      });
    }
    if (path === "/src_github" && method === "DELETE") {
      deleted.push("src_github");
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({
      status: 404,
      json: { title: "Not stubbed", status: 404, detail: `${method} ${path}` },
    });
  });

  await page.goto("/i/staging-agentos/studio/sources");
  const item = page
    .getByRole("list", { name: "Connections" })
    .getByRole("listitem", { name: "Northwind GitHub" });
  await expect(item).toContainText("Token · read & write · agnostic-bot");
  await item.getByRole("button", { name: "Verify Northwind GitHub" }).click();
  await expect.poll(() => seen.verified).toBe(1);

  await item.getByRole("button", { name: "Edit Northwind GitHub" }).click();
  const dialog = page.getByRole("dialog", { name: "Edit Northwind GitHub" });
  await dialog.getByRole("textbox", { name: "Server URL" }).fill("https://ghe.northwind.test");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
  expect(seen.patches).toEqual([{ version: 3, web_url: "https://ghe.northwind.test" }]);

  await page.getByRole("button", { name: "Disconnect source" }).click();
  await page
    .getByRole("dialog", { name: "Disconnect northwind/agent-platform · main?" })
    .getByRole("button", { name: "Disconnect" })
    .click();
  await expect(page.getByText("No code sources yet")).toBeVisible();
  expect(deleted).toEqual(["src_github"]);
});
