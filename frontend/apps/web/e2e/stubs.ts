// Shared API stubs for the e2e suites: the prototype's sample org, served by page.route.
import type { Page } from "@playwright/test";

export const T = "2026-11-01T09:00:00Z";
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
  has_client_certificate: false,
  network_mode: "gateway",
  browser_url: `http://${slug}:7777`,
  version_drift: null,
  created_at: T,
  updated_at: T,
  version: 1,
  elevation_enabled: true,
});
export const instances = [
  instance("ins_01M6A0EEZEQ373S26F2014PRD", "prod-agentos", "production"),
  instance("ins_01M6A0EEZEQ373S26F2014STG", "staging-agentos", "staging"),
];
export const me = {
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
  settings: { require_explicit_bindings: false, audit_log_all_reads: false, approval_ttl_hours: 0 },
  updated_at: T,
};
export const access = {
  instance_id: null,
  org_role: "owner",
  implicit_full_access: true,
  roles: ["Full access"],
  token_scopes: ["agent_os:admin"],
  runtime_scopes: ["agent_os:admin"],
  control_plane_scopes: [
    "org:read",
    "org:write",
    "org:members:read",
    "org:members:write",
    "org:roles:read",
    "org:roles:write",
    "org:roles:delete",
    "os:read",
    "os:write",
    "audit:read",
    "audit:export",
    "settings:read",
    "settings:write",
    "service_accounts:manage",
    "assistant:use",
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

export async function stubApi(page: Page, { signedIn = true } = {}) {
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
  // AI features are off unless a spec turns them on (assistant.spec.ts).
  await page.route(/\/api\/v1\/system\/features$/, (route) => route.fulfill({ json: { features: {} } }));
  await page.route(/\/api\/v1\/system\/modules$/, (route) =>
    route.fulfill({ json: { enabled: [], disabled: ["assistant"] } }),
  );
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
  // Realtime: a stream that says hello and ends (the client reconnects quietly).
  await page.route(/\/api\/v1\/events$/, (route) =>
    route.fulfill({ contentType: "text/event-stream", body: 'event: ready\ndata: {"instances":[]}\n\n' }),
  );
  // No badge by default: the sidebar baseline stays stable (operate.spec covers the badge).
  await page.route(/\/api\/v1\/instances\/[^/]+\/approvals\/count$/, (route) =>
    route.fulfill({ json: { instance_id: instances[0]?.id, count: null, available: false } }),
  );
  // No open code-source conflicts (no sidebar dot) and no component synced with a repository, unless a suite says so.
  await page.route(/\/api\/v1\/instances\/[^/]+\/studio\/sources\/conflicts\/count$/, (route) =>
    route.fulfill({ json: { instance_id: instances[0]?.id, count: 0 } }),
  );
  await page.route(/\/api\/v1\/instances\/[^/]+\/studio\/components\/[^/]+\/source$/, (route) =>
    route.fulfill({ json: { bound: false } }),
  );
  // The bell: nothing unread by default (suites that test notifications register their own routes after this).
  await page.route(/\/api\/v1\/notifications\/unread-count$/, (route) =>
    route.fulfill({ json: { unread: 0 } }),
  );
  await page.route(/\/api\/v1\/notifications(\?.*)?$/, (route) =>
    route.fulfill({ json: { data: [], next_cursor: null, total_estimate: null } }),
  );
  // An empty approvals inbox, so the Approvals page renders for the shell's sidebar baseline.
  await page.route(/\/api\/v1\/instances\/[^/]+\/approvals(\?.*)?$/, (route) =>
    route.fulfill({
      json: { data: [], page: 1, limit: 50, total: 0, truncated: false, oldest_pending_at: null },
    }),
  );
  await page.route(/\/api\/v1\/instances\/[^/]+\/approvals\/counts$/, (route) =>
    route.fulfill({
      json: { pending: 0, approved: 0, rejected: 0, expired: 0, cancelled: 0, truncated: false },
    }),
  );
  await page.route(/\/api\/v1\/me\/notification-preferences$/, (route) =>
    route.fulfill({ json: { events: [], quiet_hours: null, slack_available: false } }),
  );
  await page.route(/\/api\/v1\/instances\/[^/]+\/overview/, (route) =>
    route.fulfill({
      json: {
        instance_id: instances[0]?.id,
        range: "7d",
        start: T,
        end: T,
        generated_at: T,
        cached: false,
        sampled: false,
        counts: { agents: 6, teams: 3, workflows: 5 },
        kpis: null,
        runs_per_day: null,
        model_usage: null,
        primitives: null,
        pending_approvals: null,
        attention: [],
        activity: [],
        unavailable: { metrics: "Not enabled on this instance." },
      },
    }),
  );
}
