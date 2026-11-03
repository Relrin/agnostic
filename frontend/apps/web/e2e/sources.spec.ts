// Code sources against stubbed APIs: the sidebar's conflict dot, the GitHub source's incoming changes with what
// pulling does, the outgoing change with its branch and review requirement, and a conflict resolved by keeping the
// repository's value.
import { expect, test } from "@playwright/test";

import { instances, stubApi } from "./stubs";

const SOURCES = /\/api\/v1\/instances\/[^/]+\/studio\/sources/;
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

test("sources: the conflict dot, the changes and a conflict kept from the repository", async ({ page }) => {
  await stubApi(page);
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
