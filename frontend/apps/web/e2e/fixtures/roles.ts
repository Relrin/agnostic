// The roles stub: the built-in Operator and Viewer roles, the scope catalog, and a preview/save that diffs scopes.
import type { Page, Route } from "@playwright/test";

import { T, me } from "../stubs";

const OPERATOR_PERMISSIONS: Record<string, string[]> = {
  agents: ["read", "run"],
  teams: ["read", "run"],
  workflows: ["read", "run"],
  components: ["read"],
  registry: ["read"],
  sessions: ["read"],
  memories: ["read"],
  learnings: ["read"],
  knowledge: ["read"],
  traces: ["read"],
  metrics: ["read"],
  evals: ["read"],
  approvals: ["read", "write", "delete"],
  schedules: ["read", "write"],
  config: ["read"],
};

const scopesOf = (permissions: Record<string, string[]>) =>
  Object.entries(permissions)
    .flatMap(([family, actions]) => actions.map((action) => `${family}:${action}`))
    .sort();

const OPERATOR = {
  id: "rol_operator",
  slug: "operator",
  name: "Operator",
  description: "Runs and supervises live agents. Can resolve approvals; can't change definitions.",
  color: "#C5F25C",
  kind: "built_in",
  permissions: OPERATOR_PERMISSIONS,
  run_scope: {},
  bindable_instance_ids: null,
  scopes: scopesOf(OPERATOR_PERMISSIONS),
  people: 9,
  groups: 2,
  service_accounts: 0,
  version: 4,
};

const VIEWER = {
  ...OPERATOR,
  id: "rol_viewer",
  slug: "viewer",
  name: "Viewer",
  description: "Read-only.",
  color: "#A9AFB8",
  permissions: { agents: ["read"] },
  scopes: ["agents:read"],
  people: 6,
  groups: 0,
  version: 1,
};

const CATALOG = Object.entries({
  agents: ["read", "run", "write", "delete"],
  teams: ["read", "run", "write", "delete"],
  workflows: ["read", "run", "write", "delete"],
  components: ["read", "write", "delete"],
  registry: ["read"],
  sessions: ["read", "write", "delete"],
  memories: ["read", "write", "delete"],
  learnings: ["read", "write", "delete"],
  knowledge: ["read", "write", "delete"],
  traces: ["read"],
  metrics: ["read", "write"],
  evals: ["read", "write", "delete"],
  approvals: ["read", "write", "delete"],
  schedules: ["read", "write", "delete"],
  config: ["read", "write"],
  service_accounts: ["read", "write", "delete"],
}).flatMap(([family, actions]) =>
  actions.map((action) => ({
    scope: `${family}:${action}`,
    family,
    action,
    source: "agentos",
    description: `${action} ${family}`,
    resource_kind: ["agents", "teams", "workflows"].includes(family) ? "per_component" : "global",
    privileged: action === "write" || action === "delete",
    agentos_min_version: "3.1.0",
    hidden: false,
  })),
);

const REACH = {
  people: 9,
  direct_people: [],
  groups: [
    { id: "grp_support_ai", name: "Support AI" },
    { id: "grp_billing_ops", name: "Billing ops" },
  ],
  service_accounts: [],
  sentence: "9 people and 2 groups (Support AI, Billing ops)",
};

type Body = { permissions: Record<string, string[]>; version?: number };
export type Roles = { saved: Body[]; current: typeof OPERATOR };

function preview(before: typeof OPERATOR, body: Body) {
  const scopes = scopesOf(body.permissions);
  const added = scopes.filter((scope) => !before.scopes.includes(scope));
  const removed = before.scopes.filter((scope) => !scopes.includes(scope));
  return {
    role: { ...before, permissions: body.permissions, scopes },
    added,
    removed,
    lines: [
      ...added.map((text) => ({ op: "add", text })),
      ...removed.map((text) => ({ op: "remove", text })),
    ],
    reach: REACH,
    warnings: [],
    redeploy: false,
  };
}

export async function stubRoles(page: Page): Promise<Roles> {
  const state: Roles = { saved: [], current: OPERATOR };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  await page.route(/\/api\/v1\/members$/, (route) =>
    json(route, [
      {
        user_id: me.id,
        email: me.email,
        display_name: me.display_name,
        avatar_seed: "a",
        org_role: "owner",
        joined_at: T,
        joined_via: "bootstrap",
        last_active_at: T,
      },
    ]),
  );
  await page.route(/\/api\/v1\/access\/scopes$/, (route) => json(route, CATALOG));
  await page.route(/\/api\/v1\/access\/roles(\/.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const rest = url.pathname.replace(/^.*\/access\/roles\/?/, "");
    const method = route.request().method();
    if (method === "GET" && rest === "") return json(route, [state.current, VIEWER]);
    if (method === "POST" && rest === "rol_operator/preview")
      return json(route, preview(state.current, route.request().postDataJSON() as Body));
    if (method === "PATCH" && rest === "rol_operator") {
      const body = route.request().postDataJSON() as Body;
      state.saved.push(body);
      const result = preview(state.current, body);
      state.current = { ...result.role, version: state.current.version + 1 };
      return json(route, { ...result, role: state.current });
    }
    return json(route, { type: "x", title: "Not stubbed", status: 404, detail: `${method} ${rest}` }, 404);
  });
  return state;
}
