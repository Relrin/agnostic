// Audit log against a stubbed control plane: saved views filter the log, the Operator role edit shows its scope diff,
// and Maya's denied set-current is explained and answered with temporary access.
import { expect, test, type Page, type Route } from "@playwright/test";

import { instances, stubApi } from "./stubs";

const PROD = instances[0]?.id ?? "";
const at = (time: string) => `2026-10-31T${time}.381Z`;

type StubEvent = Record<string, unknown> & { id: string; decision: string; instance_id: string | null };

function event(fields: Record<string, unknown> & { id: string; decision: string }): StubEvent {
  return {
    request_id: `req_${fields.id}`,
    via: "web",
    ip: "203.0.113.24",
    client: "Control plane · web",
    resource_kind: null,
    resource_id: null,
    resource_display: null,
    instance_id: PROD,
    scope_checked: null,
    missing_scopes: [],
    response_status: 200,
    diff: null,
    links: null,
    source: "control_plane",
    source_event_id: null,
    denial_reason: null,
    can_request_access: false,
    hash: null,
    ...fields,
  };
}

const MAYA = event({
  id: "evt_maya",
  occurred_at: at("16:58:40"),
  actor: { kind: "user", id: "usr_maya", display: "Maya Chen" },
  action: "components.set_current",
  resource_display: "agents/support-triage → v4",
  decision: "denied",
  scope_checked: "components:write",
  missing_scopes: ["components:write"],
  response_status: 403,
  summary: "Tried to make draft v4 the current version of support-triage.",
  denial_reason:
    "POST /components/*/configs/*/set-current needs components:write on prod-agentos. Maya has Operator there (via Support AI), which doesn't include it.",
  can_request_access: true,
});
const OPERATOR = event({
  id: "evt_operator",
  occurred_at: at("16:42:03"),
  actor: { kind: "user", id: "usr_dana", display: "Dana Okafor" },
  action: "roles.update",
  resource_kind: "role",
  resource_id: "rol_operator",
  resource_display: "role Operator",
  instance_id: null,
  decision: "allowed",
  scope_checked: "org:roles:write",
  summary: "Changed the scopes of the Operator access role.",
  diff: {
    title: "Scopes",
    lines: [
      { op: "note", text: "agents:read" },
      { op: "add", text: "knowledge:write" },
      { op: "remove", text: "approvals:delete" },
    ],
    note: "Applied to 9 people and 2 groups on their next request. No redeploy.",
  },
  links: { role: "/access/roles?role=rol_operator" },
});
const SLACK_BOT = event({
  id: "evt_slack",
  occurred_at: at("16:20:31"),
  actor: { kind: "service_account", id: "sa:slack-bot", display: "sa:slack-bot" },
  action: "approvals.resolve",
  resource_display: "apv_7Kp4 · apply_account_credit",
  decision: "denied",
  scope_checked: "approvals:write",
  response_status: 404,
  summary: "Tried to approve a pending approval from a Slack button.",
  source: "agentos",
});
const EVENTS = [MAYA, OPERATOR, SLACK_BOT];

const VIEW = {
  id: "vw_denied_prod",
  name: "Denied in production",
  filters: { decision: "denied", instance: PROD },
  count: 2,
  count_capped: false,
  shared: true,
  owner_id: null,
  position: 0,
  editable: true,
  created_at: at("09:00:00"),
  updated_at: at("09:00:00"),
};

type Sent = { grants: Record<string, unknown>[]; queries: string[] };

async function stubAudit(page: Page): Promise<Sent> {
  const sent: Sent = { grants: [], queries: [] };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  await page.route(/\/api\/v1\/audit\//, async (route) => {
    const url = new URL(route.request().url());
    const rest = url.pathname.replace(/^.*\/api\/v1\/audit\//, "");
    if (rest === "events") {
      sent.queries.push(url.search);
      const decision = url.searchParams.get("decision");
      const instance = url.searchParams.get("instance");
      const rows = EVENTS.filter(
        (row) => (!decision || row.decision === decision) && (!instance || row.instance_id === instance),
      );
      return json(route, { data: rows, next_cursor: null });
    }
    if (rest.startsWith("events/")) {
      const found = EVENTS.find((row) => row.id === rest.slice("events/".length));
      return found ? json(route, found) : json(route, { type: "x", title: "Not found", status: 404 }, 404);
    }
    if (rest === "views") return json(route, [VIEW]);
    if (rest === "actors") return json(route, []);
    if (rest === "actions") return json(route, []);
    if (rest === "policy") return json(route, { hot_retention_days: 400 });
    if (rest === "stream-status") {
      const last = new Date(Date.now() - 2000).toISOString();
      return json(route, {
        streaming: true,
        last_event_at: last,
        sinks: [
          {
            id: "snk_1",
            name: "Splunk",
            kind: "https_webhook",
            status: "ok",
            enabled: true,
            last_event_at: last,
            last_error: null,
          },
        ],
      });
    }
    return json(route, { type: "x", title: "Not stubbed", status: 404, detail: rest }, 404);
  });
  await page.route(/\/api\/v1\/access\/explain$/, (route) =>
    json(route, {
      allowed: false,
      scope: "components:write",
      instance_id: PROD,
      missing_scopes: ["components:write"],
      explanation: "Needs components:write.",
      granted_by: [],
      alternatives: [{ kind: "instance", label: "Builder on staging-agentos", role_name: "Builder" }],
      can_request: true,
    }),
  );
  await page.route(/\/api\/v1\/access\/temporary$/, async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    sent.grants.push(body);
    return json(
      route,
      {
        id: "bnd_1",
        principal_id: body.principal_id,
        principal_kind: "user",
        instance_id: body.instance,
        role_id: null,
        scopes: body.scopes,
        reason: body.reason,
        created_at: at("17:10:00"),
        created_by: "usr_dana",
        expires_at: at("21:10:00"),
      },
      201,
    );
  });
  return sent;
}

test("audit: a saved view narrows the log and a role edit shows its scope diff", async ({ page }) => {
  await stubApi(page);
  const sent = await stubAudit(page);
  await page.goto("/access/audit");

  await expect(page.getByRole("heading", { name: "Audit log", level: 1 })).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Streaming to SIEM · HTTPS webhook · last event/ }),
  ).toHaveAttribute("href", "/org/settings/siem");
  await expect(page.getByText("Kept 400 days · append-only")).toBeVisible();
  const views = page.getByRole("group", { name: "Saved views" });
  await expect(views.getByRole("button", { name: "All events 3" })).toHaveAttribute("aria-pressed", "true");

  await views.getByRole("button", { name: "Denied in production 2" }).click();
  await expect(page).toHaveURL(/decision=denied/);
  await expect(page.getByText("2 events · Denied in production")).toBeVisible();
  expect(sent.queries.at(-1)).toContain(`instance=${PROD}`);

  await views.getByRole("button", { name: "All events" }).click();
  const table = page.getByRole("table", { name: "Audit events" });
  await table.getByRole("button", { name: "roles.update" }).click();
  await expect(page).toHaveURL(/event=evt_operator/);
  const aside = page.getByRole("complementary", { name: "Event details" });
  const diff = aside.getByRole("list", { name: "Scopes" });
  await expect(diff).toContainText("knowledge:write");
  await expect(diff).toContainText("approvals:delete");
  await expect(aside.getByRole("link", { name: /Open role/ })).toHaveAttribute(
    "href",
    "/access/roles?role=rol_operator",
  );
});

test("audit: a denial explains itself and an admin grants temporary access", async ({ page }) => {
  await stubApi(page);
  const sent = await stubAudit(page);
  await page.goto("/access/audit?event=evt_maya");

  const aside = page.getByRole("complementary", { name: "Event details" });
  await expect(aside.getByText("DENIED", { exact: true })).toBeVisible();
  const why = aside.getByRole("region", { name: "Why it was denied" });
  await expect(why).toContainText("Maya has Operator there (via Support AI)");
  await expect(why.getByRole("list", { name: "Would be allowed with" })).toContainText(
    "Builder on staging-agentos",
  );
  await why.getByRole("button", { name: "Grant temporary access…" }).click();

  const dialog = page.getByRole("dialog", { name: "Grant temporary access" });
  await expect(dialog.getByLabel("Scopes")).toHaveValue("components:write");
  await dialog.getByLabel("Reason").fill("Ship the v4 fix today");
  await dialog.getByRole("button", { name: "Grant access" }).click();
  await expect(dialog).toBeHidden();
  expect(sent.grants).toEqual([
    {
      principal_id: "usr_maya",
      instance: PROD,
      scopes: ["components:write"],
      reason: "Ship the v4 fix today",
      duration_hours: 4,
    },
  ]);
});
