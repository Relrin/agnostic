// Service accounts against a stubbed control plane: Dana opens zendesk-bridge and rotates its gateway token, then
// creates airflow-nightly with a privileged scope, confirms it and copies the token shown once.
import { expect, test, type Page, type Route } from "@playwright/test";

import { instances, stubApi } from "./stubs";

const DAY = 24 * 3600 * 1000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
const PROD = instances[0];
const prodRef = { id: PROD?.id ?? "", slug: "prod-agentos", display_name: "prod-agentos" };

/** A token-shaped value built at runtime (32 characters after the type prefix). */
function fakeToken(prefix: string): string {
  const head = prefix.startsWith("agn_pat_") ? "agn_pat_" : "agno_pat_";
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  const filler = Array.from(
    { length: 32 - (prefix.length - head.length) },
    (_, index) => alphabet[(index * 7 + 3) % alphabet.length],
  ).join("");
  return `${prefix}${filler}`;
}

const CURL =
  'curl -X POST http://prod-agentos:7777/agents/support-triage/runs \\\n  -H "Authorization: Bearer $AGNO_PAT" \\\n  -F message="Hello from a service account"';

const ROTATION_NOTE =
  "Rotate issues a new gateway token and keeps the old one valid for 24 h so callers can switch. AgentOS can't rotate a native token: rotating revokes it and creates a new one under the same name, so callers see a brief gap.";

const ZENDESK = {
  id: "sa_zendesk",
  name: "zendesk-bridge",
  principal: "sa:zendesk-bridge",
  description: "Forwards Zendesk tickets to the support agents and posts replies back.",
  created_by: { id: "usr_dana", name: "Dana Okafor" },
  created_at: ago(83 * DAY),
  forwards_user_id: true,
  scope_source: "custom",
  role_id: null,
  role_name: null,
  source_label: "Custom scopes",
  scopes: [
    "agents:support-triage:run",
    "agents:billing-agent:run",
    "teams:escalation-team:run",
    "workflows:ticket-router:run",
    "sessions:read",
    "sessions:write",
  ],
  extra_scopes: [],
  scope_count: 6,
  privileged: true,
  instances: [prodRef],
  last_used_at: ago(2000),
  expires_at: null,
  expired: false,
  expiry_warning: true,
  kinds: ["native", "gateway"],
  active_tokens: 2,
};

const SCOPE_ITEMS = ZENDESK.scopes.map((scope) => ({
  scope,
  source: "custom",
  privileged: scope === "sessions:write",
}));

const GATEWAY = {
  id: "gwt_Qm4x",
  kind: "gateway",
  prefix: "agn_pat_Qm4x",
  status: "active",
  created_at: ago(83 * DAY),
  grace_until: null as string | null,
  revoked_at: null,
  revoke_reason: null as string | null,
  last_used_at: ago(9 * 60_000),
  last_used_ip: "10.0.4.12",
};

function detail(gatewayTokens: unknown[]) {
  return {
    ...ZENDESK,
    scope_items: SCOPE_ITEMS,
    isolation_note:
      "Sends user_id per request (zd:<ticket user>), so user isolation applies to each customer.",
    native_tokens: [
      {
        id: "tok_7Hq2",
        kind: "native",
        instance: prodRef,
        prefix: "agno_pat_7Hq2",
        status: "active",
        scopes: [],
        created_at: ago(83 * DAY),
        revoked_at: null,
        expires_at: null,
        last_used_at: ago(2000),
      },
      {
        id: "tok_3Lw9",
        kind: "native",
        instance: prodRef,
        prefix: "agno_pat_3Lw9",
        status: "revoked",
        scopes: [],
        created_at: ago(200 * DAY),
        revoked_at: ago(83 * DAY),
        expires_at: null,
        last_used_at: ago(83 * DAY),
      },
    ],
    gateway_tokens: gatewayTokens,
    rotation_note: ROTATION_NOTE,
    cli_command: "agnostic tokens create zendesk-bridge \\\n  --instance prod-agentos",
  };
}

const SCOPES = [
  ["agents", "read", "See agents"],
  ["agents", "run", "Run agents"],
  ["sessions", "read", "See sessions"],
  ["metrics", "read", "See metrics"],
  ["service_accounts", "write", "Create and change native service accounts"],
].map(([family, action, description]) => ({
  scope: `${family}:${action}`,
  family,
  action,
  description,
  source: "agentos",
  resource_kind: family === "agents" ? "per_component" : "global",
  privileged: action === "write",
  hidden: false,
  agentos_min_version: "3.1.0",
}));

type State = { rotated: boolean; issued: unknown[]; created: Record<string, unknown>[] };

async function stubServiceAccounts(page: Page): Promise<State> {
  const state: State = { rotated: false, issued: [], created: [] };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  const gatewayTokens = () =>
    state.rotated
      ? [
          { ...GATEWAY, grace_until: new Date(Date.now() + DAY).toISOString(), revoke_reason: "rotated" },
          {
            ...GATEWAY,
            id: "gwt_N8de",
            prefix: "agn_pat_N8de",
            created_at: new Date().toISOString(),
            last_used_at: null,
          },
        ]
      : [GATEWAY];

  await page.route(/\/api\/v1\/access\/scopes$/, (route) => json(route, SCOPES));
  await page.route(/\/api\/v1\/access\/roles$/, (route) => json(route, []));
  await page.route(/\/api\/v1\/service-accounts(\/[^?]*)?(\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const rest = url.pathname.replace(/^.*\/service-accounts\/?/, "");
    const method = route.request().method();
    if (method === "GET" && rest === "") return json(route, [ZENDESK]);
    if (method === "GET" && rest === ZENDESK.name) return json(route, detail(gatewayTokens()));
    if (method === "POST" && rest === "preview") {
      const body = route.request().postDataJSON() as { name: string; scopes: string[] };
      const privileged = body.scopes.filter(
        (scope) => scope.endsWith(":write") || scope.startsWith("service_accounts:"),
      );
      return json(route, {
        principal: `sa:${body.name}`,
        privileged_scopes: privileged,
        expires_at: null,
        problems: [],
        token_prefixes: {},
        cli_command: [
          `agnostic tokens create ${body.name || "<name>"}`,
          "--instance prod-agentos",
          ...(body.scopes.length ? [`--scopes ${body.scopes.join(",")}`] : []),
          "--expires-in 90d",
          "--kind native",
          ...(privileged.length ? ["--yes-privileged"] : []),
        ].join(" \\\n  "),
      });
    }
    if (method === "POST" && rest === `${ZENDESK.name}/tokens`) {
      state.issued.push(route.request().postDataJSON());
      state.rotated = true;
      return json(
        route,
        {
          account: detail(gatewayTokens()),
          token: {
            id: "gwt_N8de",
            kind: "gateway",
            token: fakeToken("agn_pat_N8de"),
            prefix: "agn_pat_N8de",
            instance: null,
            expires_at: null,
            curl: CURL,
          },
          replaced_id: GATEWAY.id,
          grace_until: new Date(Date.now() + DAY).toISOString(),
        },
        201,
      );
    }
    if (method === "POST" && rest === "") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      state.created.push(body);
      const account = {
        ...ZENDESK,
        id: "sa_airflow",
        name: "airflow-nightly",
        principal: "sa:airflow-nightly",
        description: "",
        scope_count: 2,
        scopes: body.scopes,
        source_label: "Custom scopes",
        forwards_user_id: false,
        last_used_at: null,
        active_tokens: 1,
        scope_items: [],
        isolation_note: "No user_id: runs are owned by sa:airflow-nightly.",
        native_tokens: [],
        gateway_tokens: [],
        rotation_note: ROTATION_NOTE,
        cli_command: "",
      };
      return json(
        route,
        {
          account,
          tokens: [
            {
              id: "tok_Ab3d",
              kind: "native",
              token: fakeToken("agno_pat_Ab3d"),
              prefix: "agno_pat_Ab3d",
              instance: prodRef,
              expires_at: null,
              curl: CURL,
            },
          ],
        },
        201,
      );
    }
    return json(
      route,
      { type: "x", title: "Not stubbed", status: 404, code: "not_found", detail: `${method} ${rest}` },
      404,
    );
  });
  return state;
}

test("service accounts: rotate a gateway token, then create an account with a privileged scope", async ({
  page,
}) => {
  await stubApi(page);
  const state = await stubServiceAccounts(page);
  await page.goto("/access/service-accounts");

  await expect(page.getByRole("heading", { name: "Service accounts", level: 1 })).toBeVisible();
  const table = page.getByRole("table", { name: "Service accounts" });
  await expect(table.getByText("sa:zendesk-bridge")).toBeVisible();
  await expect(table.getByText("No expiry")).toBeVisible();
  await table.getByRole("button", { name: "zendesk-bridge" }).click();

  await expect(page).toHaveURL(/account=zendesk-bridge/);
  const aside = page.getByRole("complementary", { name: "Service account details" });
  await expect(aside.getByRole("listitem", { name: "Token agno_pat_7Hq2" })).toContainText("ACTIVE");
  await expect(aside.getByRole("listitem", { name: "Token agno_pat_3Lw9" })).toContainText("REVOKED");

  await aside.getByRole("button", { name: "Rotate agn_pat_Qm4x" }).click();
  const dialog = page.getByRole("dialog", { name: "Rotate agn_pat_Qm4x…?" });
  await expect(dialog).toContainText("the old one keeps working for 24 h");
  await dialog.getByRole("button", { name: "Rotate token" }).click();
  const rotated = page.getByRole("dialog", { name: "Copy the token now" });
  await expect(rotated.getByText(/^agn_pat_N8de\w{28}$/)).toBeVisible();
  expect(state.issued).toEqual([{ kind: "gateway" }]);
  await rotated.getByRole("button", { name: "I've stored it" }).click();
  await expect(aside.getByRole("listitem", { name: "Token agn_pat_Qm4x" })).toContainText("ROTATING OUT");

  await page.getByRole("button", { name: "New service account" }).click();
  const form = page.getByRole("form", { name: "New service account" });
  await form.getByLabel("Name").fill("airflow-nightly");
  await expect(form.getByText("sa:airflow-nightly", { exact: true })).toBeVisible();
  await form.getByRole("checkbox", { name: "prod-agentos" }).check();
  await form.getByRole("checkbox", { name: "agents:read" }).check();
  await form.getByRole("checkbox", { name: "service_accounts:write" }).check();
  await expect(form.getByRole("alert")).toContainText("lets this token mint new tokens");
  const submit = form.getByRole("button", { name: "Create and show token" });
  await expect(submit).toBeDisabled();
  await expect(form.getByText(/--yes-privileged/)).toBeVisible();
  await form.getByLabel("I understand this account gets privileged scopes").check();
  await submit.click();

  const shown = page.getByRole("region", { name: "New tokens" });
  await expect(shown.getByText("sa:airflow-nightly created")).toBeVisible();
  await expect(shown.getByText(/^agno_pat_Ab3d\w{28}$/)).toBeVisible();
  await expect(shown.getByText("They won't be shown again")).toBeVisible();
  expect(state.created).toEqual([
    expect.objectContaining({
      name: "airflow-nightly",
      instances: [PROD?.id],
      scopes: ["agents:read", "service_accounts:write"],
      confirm_privileged: true,
    }),
  ]);
});
