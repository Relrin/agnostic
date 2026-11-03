// People & groups against a stubbed control plane: Maya Chen gets Operator on prod through Support AI and a granular
// billing-agent grant through Billing ops. Daniel opens Maya, sees her access by instance and checks whether she can
// run billing-agent on prod; then he opens the Support AI group, synced by SCIM, with its role bindings, the approval
// route that names it and its owner.
import { expect, test, type Page, type Route } from "@playwright/test";

import { T, instances, stubApi } from "./stubs";

const PROD = instances[0]?.id ?? "";
const STAGING = instances[1]?.id ?? "";
const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const SUPPORT = { id: "grp_support", name: "Support AI" };
const BILLING = { id: "grp_billing", name: "Billing ops" };

const member = (id: string, name: string, role: string, groups: { id: string; name: string }[]) => ({
  user_id: id,
  email: `${name.split(" ")[0]?.toLowerCase() ?? "x"}@localhost.company`,
  display_name: name,
  avatar_seed: id,
  org_role: role,
  joined_at: T,
  joined_via: "sso:okta",
  last_active_at: minutesAgo(12),
  groups,
});

const MEMBERS = [
  member("usr_dana", "Daniel Okafor", "owner", []),
  member("usr_maya", "Maya Chen", "member", [SUPPORT, BILLING]),
  member("usr_priya", "Priya Nair", "member", [SUPPORT]),
  member("usr_omar", "Omar Haddad", "member", [BILLING]),
];

const role = (id: string, name: string, color: string) => ({
  id,
  slug: name.toLowerCase(),
  name,
  description: "",
  color,
  kind: "built_in",
  permissions: {},
  run_scope: {},
  bindable_instance_ids: null,
  scopes: [],
  people: 1,
  version: 1,
});
const ROLES = [role("rol_operator", "Operator", "#F2B54B"), role("rol_builder", "Builder", "#9DBBFF")];

const binding = (
  id: string,
  group: string,
  instance: string,
  roleId: string | null,
  scopes: string[] = [],
) => ({
  id,
  principal_kind: "group",
  principal_id: group,
  instance_id: instance,
  role_id: roleId,
  scopes,
  expires_at: null,
  reason: null,
  created_by: "usr_dana",
  created_at: T,
});
const BINDINGS = [
  binding("bnd_1", SUPPORT.id, PROD, "rol_operator"),
  binding("bnd_2", SUPPORT.id, STAGING, "rol_builder"),
  binding("bnd_3", BILLING.id, PROD, null, ["agents:billing-agent:run"]),
];

const group = (ref: { id: string; name: string }, external: string, count: number) => ({
  ...ref,
  description: "",
  source: "scim",
  external_id: `00g${external}`,
  external_name: external,
  sync_label: `SCIM · ${external}`,
  synced: true,
  member_count: count,
  created_at: T,
  updated_at: T,
});
const GROUPS = [group(SUPPORT, "support-ai", 2), group(BILLING, "billing", 2)];

const SCOPES = ["read", "run"].map((action) => ({
  scope: `agents:${action}`,
  family: "agents",
  action,
  source: "agentos",
  description: `${action} agents`,
  resource_kind: "per_component",
  privileged: false,
  hidden: false,
}));

const ROUTE = {
  id: "rte_refunds",
  name: "Refunds",
  instance_id: PROD,
  tool_name: "refund_customer",
  component_kind: "agent",
  component_ids: ["support-triage", "billing-agent"],
  groups: [SUPPORT],
  members: [],
  roles: [],
  channels: ["in_app"],
  channel_ids: [],
  created_by: "usr_dana",
  updated_at: T,
};

type Directory = { explained: Record<string, unknown>[] };

async function stubDirectory(page: Page): Promise<Directory> {
  const state: Directory = { explained: [] };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  await page.route(
    /\/api\/v1\/(members|access|directory|invitations|approvals\/routes\/by-group)(\/[^?]*)?(\?.*)?$/,
    async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname.replace(/^\/api\/v1\//, "");
      const method = route.request().method();
      if (method === "GET") {
        if (path === "members") return json(route, MEMBERS);
        if (path === "access/roles") return json(route, ROLES);
        if (path === "access/bindings") return json(route, BINDINGS);
        if (path === "access/scopes") return json(route, SCOPES);
        if (path === "access/requests") return json(route, []);
        if (path === "invitations") return json(route, []);
        if (path === "directory/groups") return json(route, GROUPS);
        if (path === `directory/groups/${SUPPORT.id}`)
          return json(route, {
            ...GROUPS[0],
            members: [
              {
                user_id: "usr_maya",
                display_name: "Maya Chen",
                email: "maya@localhost.company",
                role: "owner",
                source: "scim",
              },
              {
                user_id: "usr_priya",
                display_name: "Priya Nair",
                email: "priya@localhost.company",
                role: "member",
                source: "scim",
              },
            ],
          });
        if (path === `approvals/routes/by-group/${SUPPORT.id}`) return json(route, [ROUTE]);
        if (path === "directory/scim")
          return json(route, {
            endpoint_url: "http://localhost/scim/v2",
            healthy: true,
            last_error: null,
            last_error_at: null,
            last_request_at: minutesAgo(4),
            counts: {},
            tokens: [
              {
                id: "sct_okta",
                label: "Okta",
                prefix: "scim_9f2",
                state: "active",
                created_at: T,
                created_by: "usr_dana",
                expires_at: null,
                last_used_at: minutesAgo(4),
                rotated_from: null,
              },
            ],
          });
      }
      if (method === "POST" && path === "access/explain") {
        state.explained.push(route.request().postDataJSON() as Record<string, unknown>);
        return json(route, {
          allowed: true,
          scope: "agents:billing-agent:run",
          instance_id: PROD,
          granted_by: [],
          missing_scopes: [],
          alternatives: [],
          explanation: "Granted by Billing ops via Billing ops → `agents:billing-agent:run` on prod-agentos.",
          via_group: "Billing ops",
        });
      }
      return json(route, { type: "x", title: "Not stubbed", status: 404, detail: `${method} ${path}` }, 404);
    },
  );
  return state;
}

test("people: open Maya's access, check a permission, then the Support AI group", async ({ page }) => {
  await stubApi(page);
  const directory = await stubDirectory(page);
  await page.goto("/access/people");

  await expect(page.getByRole("heading", { name: "People & groups", level: 1 })).toBeVisible();
  await expect(page.getByText("Okta SCIM · synced 4 min ago")).toBeVisible();
  const table = page.getByRole("table", { name: "Members" });
  const maya = table.getByRole("row").filter({ hasText: "Maya Chen" });
  await expect(maya.getByText("via Support AI")).toHaveCount(2);
  await expect(maya.getByText("agents:billing-agent:run")).toBeVisible();

  await table.getByRole("button", { name: "Maya Chen" }).click();
  await expect(page).toHaveURL(/member=usr_maya/);
  const aside = page.getByRole("dialog", { name: "Maya Chen" });
  await expect(aside.getByRole("listitem", { name: "Access on prod-agentos" })).toContainText("Operator");
  await expect(aside.getByText(/User isolation is on for prod-agentos/)).toBeVisible();

  await aside.getByRole("combobox", { name: "Resource" }).click();
  await page.getByRole("option", { name: "agents" }).click();
  await aside.getByRole("combobox", { name: "Action" }).click();
  await page.getByRole("option", { name: "run" }).click();
  await aside.getByLabel("Agent id").fill("billing-agent");
  await aside.getByRole("button", { name: "Check" }).click();
  await expect(aside.getByRole("status")).toContainText("Yes. Granted by Billing ops via Billing ops");
  expect(directory.explained).toEqual([
    { user_id: "usr_maya", resource: "agents", verb: "run", component: "billing-agent", instance: PROD },
  ]);

  await aside.getByRole("button", { name: "Support AI" }).first().click();
  await expect(page).toHaveURL(/tab=groups/);
  await expect(page).toHaveURL(/group=grp_support/);
  const groupAside = page.getByRole("dialog", { name: "Support AI" });
  await expect(groupAside.getByText(/synced from support-ai/)).toBeVisible();
  await expect(groupAside.getByRole("list", { name: "Role bindings" })).toContainText("Operator");
  await expect(groupAside.getByRole("list", { name: "Approval routes" })).toContainText("refund_customer");
  await expect(groupAside.getByRole("list", { name: "Group members" })).toContainText("owner");
});
