// Code sources fixtures from the design (northwind/agent-platform on GitHub with two incoming changes, one outgoing
// and a conflict on billing_agent's instructions[2]; a read-only GitLab source; a local folder) and their handlers.
import type {
  ChangeOut,
  ChangesOut,
  CodeSourceOut,
  ConflictOut,
  MappingOut,
  PullResultOut,
  SyncPolicyIo,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";

const POLICY: SyncPolicyIo = {
  pull_mode: "on_demand",
  publish_mode: "open_pr",
  branch_template: "studio/{component}-v{version}",
  commit_template: "{component}: {summary}",
  block_publish_until_merged: false,
};

const MAPPINGS: MappingOut[] = [
  { glob: "agents/*.py", target_kind: "agents", writable: true, count: 6 },
  { glob: "teams/*.py", target_kind: "teams", writable: true, count: 3 },
  { glob: "workflows/*.py", target_kind: "workflows", writable: true, count: 5 },
  { glob: "registry.py", target_kind: "registry", writable: false, count: 1 },
  { glob: "tests/, utils/", target_kind: "ignored", writable: false, count: 4 },
];

function source(overrides: Partial<CodeSourceOut>): CodeSourceOut {
  return {
    id: "src_github",
    instance_id: "ins_staging",
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
    last_fetched_at: "2026-11-03T09:00:00Z",
    mappings: MAPPINGS,
    policy: POLICY,
    convention: null,
    incoming: 2,
    outgoing: 1,
    conflicts: 1,
    open_pull_requests: 0,
    webhook: true,
    version: 3,
    ...overrides,
  };
}

export const sampleSources: CodeSourceOut[] = [
  source({}),
  source({
    id: "src_gitlab",
    provider: "gitlab",
    provider_label: "GitLab",
    repo: "northwind/data-agents",
    branch: "release/2026.11",
    connection_id: "scn_gitlab",
    connection_name: "Northwind GitLab",
    auth: "Deploy key · pull only",
    incoming: 0,
    outgoing: 0,
    conflicts: 0,
    webhook: false,
    policy: { ...POLICY, publish_mode: "no_write_back" },
  }),
  source({
    id: "src_local",
    provider: "local",
    provider_label: "Local folder",
    repo: "/app/agents",
    branch: "local",
    local_path: "/app/agents",
    connection_id: null,
    connection_name: null,
    auth: "Local folder · writes go straight to disk",
    incoming: 0,
    outgoing: 0,
    conflicts: 0,
    webhook: false,
    mappings: [{ glob: "agents/*.py", target_kind: "agents", writable: true, count: 18 }],
  }),
];

function change(overrides: Partial<ChangeOut>): ChangeOut {
  return {
    id: "sch_1",
    direction: "incoming",
    path: "workflows/ticket_router.py",
    component_kind: "workflow",
    component_id: "ticket-router",
    commit_sha: "7c2e1f0aa11b22c33d44e55f66a77b88c99d00e1",
    author_name: "Sam Rivera",
    committed_at: "2026-11-03T07:00:00Z",
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
    ...overrides,
  };
}

export const sampleConflict: ConflictOut = {
  id: "scf_1",
  change_id: "sch_3",
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

export const sampleChanges: ChangesOut = {
  remote: {
    ref: "origin/main",
    head_sha: "9f03b77c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f60",
    fetched_at: "2026-11-03T08:59:00Z",
  },
  incoming: [
    change({}),
    change({
      id: "sch_2",
      path: "agents/kb_researcher.py",
      component_kind: "agent",
      component_id: "kb-researcher",
      commit_sha: "3b9d2aa0000000000000000000000000000000000",
      author_name: "Lena Ito",
      message: "Raise retriever top_k to 8",
      additions: 1,
      deletions: 1,
      outcome: { action: "new_draft", version: 9 },
      outcome_sentence: "Becomes draft v9 of kb-researcher",
    }),
  ],
  outgoing: [
    change({
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
    }),
  ],
  conflicts: [sampleConflict],
  pull_requests: [],
};

export type SourcesCalls = {
  pulls: string[][];
  resolutions: { conflict: string; resolution: string }[];
  commits: { change_ids: string[]; message: string | null | undefined }[];
  includes: { change: string; included: boolean }[];
  updates: Record<string, unknown>[];
};

export function sourcesCalls(): SourcesCalls {
  return { pulls: [], resolutions: [], commits: [], includes: [], updates: [] };
}

export function sourcesHandlers(
  calls: SourcesCalls = sourcesCalls(),
  sources: CodeSourceOut[] = sampleSources,
) {
  const base = `${API}/instances/:instance/studio/sources`;
  return [
    http.get(`${base}/conflicts/count`, () => HttpResponse.json({ instance_id: "ins_staging", count: 1 })),
    http.get(base, () => HttpResponse.json(sources)),
    http.get(`${base}/:sourceId`, ({ params }) => {
      const found = sources.find((item) => item.id === params.sourceId);
      return found ? HttpResponse.json(found) : HttpResponse.json({ code: "not_found" }, { status: 404 });
    }),
    http.patch(`${base}/:sourceId`, async ({ params, request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      calls.updates.push(body);
      const found = sources.find((item) => item.id === params.sourceId) ?? sources[0];
      return HttpResponse.json({ ...found, ...(body.policy ? { policy: body.policy } : {}) });
    }),
    http.get(`${base}/:sourceId/changes`, ({ params }) =>
      HttpResponse.json(
        params.sourceId === "src_github"
          ? sampleChanges
          : { ...sampleChanges, incoming: [], outgoing: [], conflicts: [], pull_requests: [] },
      ),
    ),
    http.patch(`${base}/:sourceId/changes/:changeId`, async ({ params, request }) => {
      const body = (await request.json()) as { included: boolean };
      calls.includes.push({ change: String(params.changeId), included: body.included });
      const found = [...sampleChanges.incoming, ...sampleChanges.outgoing].find(
        (item) => item.id === params.changeId,
      );
      return HttpResponse.json({ ...found, included: body.included });
    }),
    http.post(`${base}/:sourceId/pull`, async ({ request }) => {
      const body = (await request.json()) as { change_ids: string[] };
      calls.pulls.push(body.change_ids);
      const results: PullResultOut[] = body.change_ids.map((id, index) => ({
        change_id: id,
        path: "workflows/ticket_router.py",
        component_id: "ticket-router",
        version: 9 + index,
        error: null,
      }));
      return HttpResponse.json(results);
    }),
    http.post(`${base}/:sourceId/fetch`, () => HttpResponse.json({ job_id: 7 }, { status: 202 })),
    http.post(`${base}/:sourceId/outgoing/refresh`, () => HttpResponse.json(sampleChanges.outgoing)),
    http.get(`${base}/:sourceId/commit-preview`, () =>
      HttpResponse.json({
        branch: "studio/support-triage-v4",
        base_branch: "main",
        mode: "open_pr",
        message: "support-triage: lower temperature, add refund rule",
        review_requirement: "1 review from Platform required",
        sentence: "Branch studio/support-triage-v4 · PR into main · 1 review from Platform required",
      }),
    ),
    http.post(`${base}/:sourceId/commit`, async ({ request }) => {
      const body = (await request.json()) as { change_ids: string[]; message?: string | null };
      calls.commits.push({ change_ids: body.change_ids, message: body.message });
      return HttpResponse.json({ job_id: 8 }, { status: 202 });
    }),
    http.post(`${base}/:sourceId/conflicts/:conflictId/resolve`, async ({ params, request }) => {
      const body = (await request.json()) as { resolution: string };
      calls.resolutions.push({ conflict: String(params.conflictId), resolution: body.resolution });
      return HttpResponse.json({ ...sampleConflict, status: "resolved", resolution: body.resolution });
    }),
    http.get(`${API}/studio/connections`, () => HttpResponse.json([])),
  ];
}
