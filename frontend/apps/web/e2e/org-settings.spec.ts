// Organization settings against a stubbed control plane: Dana adds a SAML provider (confirming it's her first),
// copies the SP details, then issues a SCIM token that is shown once.
import { expect, test, type Page, type Route } from "@playwright/test";

import { T, stubApi } from "./stubs";

/** A fake SCIM token, built at runtime so secret scanners don't flag the fixture. */
const SCIM_SECRET = ["agn_scim_7Hq2", "e2eSECRET"].join("_");

const ORIGIN = "http://localhost:5173";

const GITHUB = {
  id: "github",
  kind: "oidc",
  preset: "github",
  display_name: "GitHub",
  enabled: true,
  managed_by: "config",
  allowed_email_domains: [],
  jit_provisioning: false,
  trust_unverified_email: false,
  created_by: null,
  created_at: null,
  updated_at: null,
  oidc: {
    issuer: null,
    base_url: null,
    client_id: "Iv1.8a61",
    has_client_secret: true,
    scopes: [],
    callback_url: `${ORIGIN}/api/v1/auth/sso/github/callback`,
  },
  saml: null,
};

type State = { providers: Record<string, unknown>[]; created: unknown[]; stepUps: number; tokens: unknown[] };

async function stubOrgSettings(page: Page): Promise<State> {
  const state: State = { providers: [GITHUB], created: [], stepUps: 0, tokens: [] };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  await page.route(/\/api\/v1\/auth\/admin\/providers$/, async (route) => {
    if (route.request().method() === "GET") return json(route, state.providers);
    const body = route.request().postDataJSON() as Record<string, unknown>;
    if (state.stepUps === 0)
      return route.fulfill({
        status: 403,
        contentType: "application/problem+json",
        json: {
          type: "x",
          title: "Confirm it's you",
          status: 403,
          code: "reauth_required",
          reauth_window_seconds: 600,
        },
      });
    state.created.push(body);
    const id = String(body.id);
    const provider = {
      ...GITHUB,
      id,
      kind: "saml",
      preset: "saml",
      display_name: body.display_name,
      managed_by: "database",
      oidc: null,
      saml: {
        idp_entity_id: "http://www.okta.com/exk1",
        sso_url: "https://acme.okta.com/sso/saml",
        metadata_url: body.metadata_url,
        name_id_format: "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        attribute_mapping: { email: "email", name: null, groups: null },
        certificates: [],
        sp_entity_id: `${ORIGIN}/api/v1/auth/sso/${id}/metadata`,
        acs_url: `${ORIGIN}/api/v1/auth/sso/${id}/acs`,
      },
    };
    state.providers.push(provider);
    return json(route, provider, 201);
  });
  await page.route(/\/api\/v1\/auth\/admin\/policy$/, (route) =>
    json(route, {
      enforce_sso: false,
      break_glass_user_id: null,
      break_glass_user: null,
      session_idle_minutes: null,
      session_absolute_hours: null,
      default_session_idle_minutes: 720,
      default_session_absolute_hours: 168,
      mfa_policy: "optional",
      updated_by: null,
      updated_at: null,
    }),
  );
  await page.route(/\/api\/v1\/members$/, (route) => json(route, []));
  await page.route(/\/api\/v1\/auth\/step-up$/, (route) => {
    if (route.request().method() === "POST") state.stepUps += 1;
    return json(route, {
      authenticated_at: T,
      recent: state.stepUps > 0,
      expires_at: null,
      methods: ["password"],
      sso_providers: [],
    });
  });
  await page.route(/\/api\/v1\/directory\/scim$/, (route) =>
    json(route, {
      endpoint_url: `${ORIGIN}/scim/v2`,
      healthy: true,
      last_request_at: new Date(Date.now() - 4 * 60_000).toISOString(),
      last_error: null,
      last_error_at: null,
      counts: { users: 22, groups: 6 },
      tokens: state.tokens,
    }),
  );
  await page.route(/\/api\/v1\/directory\/scim\/tokens$/, (route) => {
    const body = route.request().postDataJSON() as { label: string };
    const token = {
      id: "sct_1",
      label: body.label,
      prefix: "agn_scim_7Hq2",
      state: "active",
      created_by: "usr_dana",
      created_at: T,
      last_used_at: null,
      expires_at: null,
      rotated_from: null,
    };
    state.tokens.push(token);
    return json(route, { token, secret: SCIM_SECRET }, 201);
  });
  await page.route(/\/api\/v1\/directory\/mapping-rules$/, (route) => json(route, []));
  await page.route(/\/api\/v1\/directory\/groups$/, (route) => json(route, []));
  await page.route(/\/api\/v1\/directory\/settings$/, (route) => json(route, { deprovision: "disable" }));
  await page.route(/\/api\/v1\/directory\/google$/, (route) =>
    json(route, {
      configured: false,
      client_email: null,
      admin_subject: null,
      customer_id: null,
      group_filter: [],
      enabled: false,
      last_run_at: null,
      last_error: null,
      counts: {},
    }),
  );
  return state;
}

test("org settings: add a SAML provider after confirming it's you, then issue a SCIM token", async ({
  page,
}) => {
  await stubApi(page);
  const state = await stubOrgSettings(page);
  await page.goto("/org/settings");

  await expect(page.getByRole("heading", { name: "Organization settings", level: 1 })).toBeVisible();
  const table = page.getByRole("table", { name: "Identity providers" });
  await expect(table.getByText("Config · read only")).toBeVisible();

  await page.getByRole("button", { name: "Add provider" }).click();
  const dialog = page.getByRole("dialog", { name: "Add an identity provider" });
  await dialog.getByRole("radio", { name: "SAML 2.0" }).click();
  await dialog.getByLabel("ID", { exact: true }).fill("okta-saml");
  await dialog.getByLabel("Display name").fill("Okta");
  await dialog.getByLabel("Metadata URL").fill("https://acme.okta.com/app/exk1/sso/saml/metadata");
  await dialog.getByRole("button", { name: "Add provider" }).click();

  const confirm = page.getByRole("dialog", { name: "Confirm it's you" });
  await confirm.getByLabel("Password").fill("correct horse battery staple");
  await confirm.getByRole("button", { name: "Confirm" }).click();

  await expect(page.getByRole("textbox", { name: "ACS URL" })).toHaveValue(
    `${ORIGIN}/api/v1/auth/sso/okta-saml/acs`,
  );
  expect(state.created).toHaveLength(1);
  expect(state.created[0]).toMatchObject({
    id: "okta-saml",
    kind: "saml",
    metadata_url: "https://acme.okta.com/app/exk1/sso/saml/metadata",
  });
  await page.getByRole("button", { name: "Close" }).first().click();
  await expect(table.getByText("okta-saml")).toBeVisible();

  await page.getByRole("tab", { name: "Directory sync" }).click();
  await expect(page).toHaveURL(/\/org\/settings\/directory$/);
  await expect(page.getByText("SCIM · synced 4 min ago")).toBeVisible();
  await page.getByLabel("New token label").fill("Okta");
  await page.getByRole("button", { name: "Create token" }).click();
  const secret = page.getByRole("dialog", { name: "SCIM token · Okta" });
  await expect(secret.getByText(SCIM_SECRET)).toBeVisible();
  await secret.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText(SCIM_SECRET)).toBeHidden();
  await expect(page.getByRole("table", { name: "SCIM tokens" }).getByText("Okta")).toBeVisible();
});
