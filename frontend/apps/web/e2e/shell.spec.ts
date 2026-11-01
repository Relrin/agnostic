import { expect, test, type Page } from "@playwright/test";

const T = "2026-11-01T09:00:00Z";
const instance = (id: string, slug: string, env: string) => ({
  id,
  slug,
  display_name: slug,
  env_tag: env,
  endpoint_url: `http://${slug}:7777`,
  os_id: `${slug}-os`,
  agno_version: "3.1.12",
  os_version: "3.1.12",
  auth_mode: "jwt",
  user_isolation: true,
  status: "connected",
  last_seen_at: T,
  latency_ms: 38,
  sub_claim_mode: "user_id",
  tls_verify: true,
  has_ca_bundle: false,
  has_security_key: false,
  version_drift: null,
  created_at: T,
  updated_at: T,
  version: 1,
});
const instances = [
  instance("ins_01M6A0EEZEQ373S26F2014PRD", "prod-agentos", "production"),
  instance("ins_01M6A0EEZEQ373S26F2014STG", "staging-agentos", "staging"),
];
const me = {
  id: "usr_dana",
  email: "daniel@localhost.company",
  display_name: "Daniel Okafor",
  avatar_seed: "a",
  locale: null,
  timezone: null,
  org_role: "owner",
  preferences: {},
  has_password: true,
  sso_providers: [],
  session_method: "password",
  created_at: T,
  last_active_at: T,
};
const org = {
  name: "Localhost Company",
  slug: "localhost-company",
  logo_url: null,
  plan_label: null,
  seat_limit: 24,
  member_count: 24,
  pending_invitations: 0,
  viewer_role: "owner",
  settings: { require_explicit_bindings: false, audit_log_all_reads: false },
  updated_at: T,
};
const access = {
  instance_id: null,
  org_role: "owner",
  implicit_full_access: true,
  roles: ["Full access"],
  token_scopes: ["agent_os:admin"],
  runtime_scopes: ["agent_os:admin"],
  control_plane_scopes: [
    "org:read",
    "org:members:read",
    "org:members:write",
    "os:read",
    "os:write",
    "audit:read",
  ],
  grants: [],
};
const events = {
  data: [
    {
      id: "evt_01M6A0EEZEQ373S26F20142E01",
      occurred_at: T,
      request_id: "req_1",
      actor: { kind: "user", id: "usr_dana", display: "Daniel Okafor" },
      via: "web",
      ip: "10.0.0.2",
      client: "Chrome",
      action: "auth.login",
      resource_kind: "user",
      resource_id: "usr_dana",
      resource_display: "daniel@localhost.company",
      instance_id: null,
      decision: "n_a",
      scope_checked: null,
      missing_scopes: [],
      response_status: null,
      summary: "Daniel Okafor signed in (password)",
      diff: null,
      links: null,
      source: "control_plane",
    },
  ],
  next_cursor: null,
};

async function stubApi(page: Page, { signedIn = true } = {}) {
  await page.route(/\/api\/v1\/me$/, (route) =>
    signedIn
      ? route.fulfill({ json: me })
      : route.fulfill({
          status: 401,
          contentType: "application/problem+json",
          json: { type: "x", title: "Sign in required", status: 401, code: "unauthenticated" },
        }),
  );
  await page.route(/\/api\/v1\/me\/access/, (route) => route.fulfill({ json: access }));
  await page.route(/\/api\/v1\/org$/, (route) => route.fulfill({ json: org }));
  await page.route(/\/api\/v1\/instances$/, (route) => route.fulfill({ json: instances }));
  await page.route(/\/api\/v1\/instances\/[^/]+\/health$/, (route) =>
    route.fulfill({
      json: {
        instance_id: instances[0]?.id,
        status: "connected",
        latency_ms: 38,
        last_seen_at: T,
        agno_version: "3.1.12",
        version_drift: null,
        capabilities: [],
        probed_at: T,
      },
    }),
  );
  await page.route(/\/api\/v1\/auth\/providers$/, (route) =>
    route.fulfill({ json: { local_login: true, providers: [] } }),
  );
  await page.route(/\/api\/v1\/onboarding\/status$/, (route) =>
    route.fulfill({ json: { org_exists: true, owner_exists: true, org_name: "Localhost Company" } }),
  );
  await page.route(/\/api\/v1\/audit\/events/, (route) => route.fulfill({ json: events }));
}

test("anonymous visitors are sent to sign in", async ({ page }) => {
  await stubApi(page, { signedIn: false });
  await page.goto("/access/people");
  await expect(page).toHaveURL(/\/login\?next=/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("opens the last instance and renders the shell", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/i\/prod-agentos\/settings$/);
  const nav = page.getByRole("navigation", { name: "Primary" });
  for (const label of [
    "Home",
    "Chat",
    "Agents",
    "Sessions",
    "Memory",
    "Approvals",
    "People & groups",
    "Settings",
  ]) {
    await expect(nav.getByRole("link", { name: label })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Switch AgentOS instance" })).toContainText("prod-agentos");
  await expect(page.getByRole("status").filter({ hasText: "Healthy" })).toContainText("38 ms · agno 3.1.12");
  await expect(page.getByText("Localhost Company")).toBeVisible();
});

test("the audit log reads from the API", async ({ page }) => {
  await stubApi(page);
  await page.goto("/access/audit");
  await expect(page.getByText("Daniel Okafor signed in (password)")).toBeVisible();
  await expect(page.getByRole("link", { name: "Audit log" })).toHaveAttribute("aria-current", "page");
});

test("command palette jumps to a page", async ({ page }) => {
  await stubApi(page);
  await page.goto("/i/prod-agentos/home");
  await page.getByRole("button", { name: /Search or jump to/ }).click();
  await page.getByPlaceholder("Search or jump to…").fill("audit log");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/access\/audit$/);
});

test("sidebar matches the visual baseline @visual", async ({ page }) => {
  await stubApi(page);
  await page.goto("/i/prod-agentos/approvals");
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  await expect(page.locator("aside")).toHaveScreenshot("sidebar.png");
});
