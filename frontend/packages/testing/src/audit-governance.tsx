// Audit log fixtures from the prototype's sample org on 31 Oct: ten events (a denied set-current for Maya, the
// Operator role edit with its scope diff, a scoped service account denied an approval…), saved views with counts,
// the actor list and vocabulary, SIEM streaming status, the retention policy, exports and the explain engine; plus
// MSW handlers that filter events the way the API does and record what the page sends.
import type {
  AccessRequestOut,
  ActorSummaryOut,
  AuditActionOut,
  AuditEventOut,
  AuditPolicyOut,
  BindingOut,
  ExplanationOut,
  ExportOut,
  MyAccessOut,
  SavedViewOut,
  StreamStatusOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { DANIEL, PROD, STAGING, ownerAccess } from "./p01";

const DAY = "2026-10-31";
const at = (time: string) => `${DAY}T${time}.381Z`;

const MAYA = "usr_01M6A0EEZEQ373S26F2014MAYA";
const DANA = "usr_01M6A0EEZEQ373S26F2014DANA";
const SAM = "usr_01M6A0EEZEQ373S26F20142SAM";
const JONAS = "usr_01M6A0EEZEQ373S26F2014JONS";
const PRIYA = "usr_01M6A0EEZEQ373S26F2014PRIY";

function auditEvent(
  fields: Partial<AuditEventOut> &
    Pick<AuditEventOut, "id" | "occurred_at" | "actor" | "action" | "summary" | "decision">,
): AuditEventOut {
  return {
    request_id: `req_${fields.id.slice(-6)}`,
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
    hash: `sha256:${fields.id.slice(-8).toLowerCase()}`,
    ...fields,
  };
}

export const AUDIT_MAYA_DENIAL =
  "POST /components/*/configs/*/set-current needs components:write on prod-agentos. Maya has Operator there (via Support AI), which doesn't include it. She is Builder on staging-agentos, where it would be allowed.";

export const sampleAuditEvents: AuditEventOut[] = [
  auditEvent({
    id: "evt_01JBX9T3K2W7A01",
    occurred_at: at("17:04:12"),
    actor: { kind: "service_account", id: "sa:zendesk-bridge", display: "sa:zendesk-bridge" },
    via: "pat",
    client: "agno-python 2.4.1",
    action: "runs.create",
    resource_kind: "agent",
    resource_id: "support-triage",
    resource_display: "agents/support-triage",
    decision: "allowed",
    scope_checked: "agents:support-triage:run",
    summary: "Started a background run for ticket user zd:50294.",
    links: { run_id: "run_7d23b4" },
    source: "agentos",
    source_event_id: "authz_7d23b4",
  }),
  auditEvent({
    id: "evt_01JBX9T3K2W7A02",
    occurred_at: at("16:58:40"),
    actor: { kind: "user", id: MAYA, display: "Maya Chen" },
    via: "gateway",
    action: "components.set_current",
    resource_kind: "component",
    resource_id: "support-triage",
    resource_display: "agents/support-triage → v4",
    decision: "denied",
    scope_checked: "components:write",
    missing_scopes: ["components:write"],
    response_status: 403,
    summary: "Tried to make draft v4 the current version of support-triage.",
    denial_reason: AUDIT_MAYA_DENIAL,
    can_request_access: true,
  }),
  auditEvent({
    id: "evt_01JBX9T3K2W7A03",
    occurred_at: at("16:52:30"),
    actor: { kind: "user", id: DANA, display: "Dana Okafor" },
    action: "components.set_current",
    resource_kind: "component",
    resource_id: "ticket-router",
    resource_display: "workflows/ticket-router → v7",
    decision: "allowed",
    scope_checked: "components:write",
    summary: "Made v7 the current version of ticket-router. The API serves it from the next request.",
    diff: {
      title: "Current version",
      lines: [
        { op: "remove", text: "ticket-router v6" },
        { op: "add", text: "ticket-router v7" },
      ],
      note: "Previous version stays available to roll back.",
    },
  }),
  auditEvent({
    id: "evt_01JBX9T3K2W7A04",
    occurred_at: at("16:42:03"),
    actor: { kind: "user", id: DANA, display: "Dana Okafor" },
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
        { op: "note", text: "agents:run" },
        { op: "add", text: "knowledge:write" },
        { op: "remove", text: "approvals:delete" },
        { op: "note", text: "… 15 unchanged" },
      ],
      note: "Applied to 9 people and 2 groups on their next request. No redeploy.",
      version: 4,
    },
    links: { role: "/access/roles?role=rol_operator" },
  }),
  auditEvent({
    id: "evt_01JBX9T3K2W7A05",
    occurred_at: at("16:20:31"),
    actor: { kind: "service_account", id: "sa:slack-bot", display: "sa:slack-bot" },
    via: "pat",
    client: "slack-bolt 1.21",
    action: "approvals.resolve",
    resource_kind: "approval",
    resource_id: "apv_7Kp4",
    resource_display: "apv_7Kp4 · apply_account_credit",
    decision: "denied",
    scope_checked: "approvals:write",
    response_status: 404,
    summary: "Tried to approve a pending approval from a Slack button.",
    denial_reason:
      "Scoped service accounts can't resolve approvals, and sa:slack-bot only holds approvals:read. The Slack button should hand off to a signed-in person instead.",
    source: "agentos",
  }),
  auditEvent({
    id: "evt_01JBX9T3K2W7A06",
    occurred_at: at("16:05:18"),
    actor: { kind: "user", id: SAM, display: "Sam Rivera" },
    action: "groups.update",
    resource_kind: "group",
    resource_id: "grp_billing_ops",
    resource_display: "group Billing ops",
    instance_id: null,
    decision: "allowed",
    scope_checked: "org:roles:write",
    summary: "Added a per-agent grant to the Billing ops group on prod-agentos.",
    diff: {
      title: "Bindings on prod-agentos",
      lines: [
        { op: "note", text: "Operator" },
        { op: "add", text: "agents:billing-agent:run" },
      ],
      note: "Affects 4 members of Billing ops.",
    },
    links: { group: "/access/people?tab=groups&group=grp_billing_ops" },
  }),
  auditEvent({
    id: "evt_01JBX9T3K2W7A07",
    occurred_at: at("15:01:22"),
    actor: { kind: "user", id: MAYA, display: "Maya Chen" },
    action: "approvals.resolve",
    resource_kind: "approval",
    resource_id: "apv_7Jz1",
    resource_display: "apv_7Jz1 · refund_customer",
    decision: "allowed",
    scope_checked: "approvals:write",
    summary: "Approved a $49.00 refund on billing-agent. The run continued and completed.",
    diff: { before: { status: "pending", amount: 49 }, after: { status: "approved", amount: 49 } },
    links: { run_id: "run_4471a", session_id: "ses_4471a", continue: "continued" },
  }),
  auditEvent({
    id: "evt_01JBX9T3K2W7A08",
    occurred_at: at("14:10:09"),
    actor: { kind: "user", id: JONAS, display: "Jonas Weber" },
    via: "gateway",
    action: "sessions.delete",
    resource_kind: "session",
    resource_id: "ses_3301c",
    resource_display: "ses_3301c",
    decision: "denied",
    scope_checked: "sessions:delete",
    missing_scopes: ["sessions:delete"],
    response_status: 403,
    summary: "Tried to delete a session from the Sessions page.",
    can_request_access: true,
  }),
  auditEvent({
    id: "evt_01JBX9T3K2W7A09",
    occurred_at: at("14:05:37"),
    actor: { kind: "user", id: PRIYA, display: "Priya Nair" },
    client: "Control plane · Studio",
    action: "components.configs.create",
    resource_kind: "component",
    resource_id: "support-triage",
    resource_display: "agents/support-triage draft v4",
    instance_id: STAGING,
    decision: "allowed",
    scope_checked: "components:write",
    summary: "Saved draft v4 of support-triage in Studio.",
    diff: {
      title: "Config changes vs v3",
      lines: [
        { op: "-", text: "temperature: 0.7" },
        { op: "+", text: "temperature: 0.2" },
        { op: "+", text: 'instructions[2]: "Never promise refunds; use refund_customer."' },
      ],
      note: "Not yet committed to GitHub.",
    },
  }),
  auditEvent({
    id: "evt_01JBX9T3K2W7A10",
    occurred_at: at("03:00:00"),
    actor: { kind: "system", id: "scheduler", display: "scheduler" },
    via: "scheduler",
    ip: "internal",
    client: "AgentOS scheduler",
    action: "runs.create",
    resource_kind: "workflow",
    resource_id: "daily-brief",
    resource_display: "workflows/daily-brief",
    decision: "allowed",
    scope_checked: "schedule daily-brief",
    summary: "Scheduled run started by daily-brief. It later failed with a timeout in web_search.",
    links: { schedule: "/i/prod-agentos/scheduler?schedule=daily-brief", run_id: "run_c47e90" },
    source: "agentos",
  }),
];

function savedView(
  fields: Partial<SavedViewOut> & Pick<SavedViewOut, "id" | "name" | "filters" | "count" | "position">,
): SavedViewOut {
  return {
    count_capped: false,
    created_at: at("09:00:00"),
    updated_at: at("09:00:00"),
    editable: true,
    owner_id: null,
    shared: true,
    ...fields,
  };
}

export const sampleAuditViews: SavedViewOut[] = [
  savedView({
    id: "vw_denied_prod",
    name: "Denied in production",
    filters: { decision: "denied", instance: PROD },
    count: 3,
    position: 0,
  }),
  savedView({
    id: "vw_roles",
    name: "Role & permission changes",
    filters: { action: "roles.*" },
    count: 2,
    position: 1,
  }),
  savedView({
    id: "vw_approvals",
    name: "Approvals resolved",
    filters: { action: "approvals.resolve" },
    count: 2,
    position: 2,
  }),
  savedView({
    id: "vw_service_accounts",
    name: "Service accounts",
    filters: { actor_kind: "service_account" },
    count: 2,
    position: 3,
    shared: false,
    owner_id: DANIEL,
  }),
];

export const sampleAuditActors: ActorSummaryOut[] = [
  { kind: "user", id: MAYA, display: "Maya Chen", count: 2 },
  { kind: "user", id: DANA, display: "Dana Okafor", count: 2 },
  { kind: "service_account", id: "sa:zendesk-bridge", display: "sa:zendesk-bridge", count: 1 },
  { kind: "service_account", id: "sa:slack-bot", display: "sa:slack-bot", count: 1 },
  { kind: "user", id: SAM, display: "Sam Rivera", count: 1 },
  { kind: "user", id: JONAS, display: "Jonas Weber", count: 1 },
  { kind: "user", id: PRIYA, display: "Priya Nair", count: 1 },
  { kind: "system", id: "scheduler", display: "scheduler", count: 1 },
];

export const sampleAuditActions: AuditActionOut[] = [
  "approvals.resolve",
  "components.configs.create",
  "components.set_current",
  "groups.update",
  "roles.update",
  "runs.create",
  "sessions.delete",
].map((action) => ({ action, summary_template: `{actor}: ${action} {resource}` }));

export const sampleAuditPolicy: AuditPolicyOut = {
  access_key_id: null,
  archive_enabled: false,
  archive_retention_days: null,
  bucket: null,
  endpoint: null,
  has_secret: false,
  hash_chain: true,
  hot_retention_days: 400,
  last_archive_at: null,
  last_archive_error: null,
  object_lock_mode: "off",
  prefix: "audit/",
  region: "us-east-1",
  updated_at: null,
  updated_by: null,
};

/** Streaming to one HTTPS webhook; the last event left `secondsAgo` seconds before the request. */
export function sampleStreamStatus(secondsAgo = 2): StreamStatusOut {
  const last = new Date(Date.now() - secondsAgo * 1000).toISOString();
  return {
    streaming: true,
    last_event_at: last,
    sinks: [
      {
        id: "snk_splunk",
        name: "Splunk HEC",
        kind: "https_webhook",
        status: "ok",
        enabled: true,
        last_event_at: last,
        last_error: null,
      },
    ],
  };
}

export const sampleJonasExplanation: ExplanationOut = {
  allowed: false,
  scope: "sessions:delete",
  instance_id: PROD,
  missing_scopes: ["sessions:delete"],
  explanation:
    "DELETE /sessions/* needs sessions:delete. Jonas has Viewer on prod-agentos (via Finance), which is read-only.",
  granted_by: [],
  alternatives: [
    { kind: "role", label: "Operator on prod-agentos", role_name: "Operator" },
    { kind: "instance", label: "Builder on staging-agentos", role_name: "Builder" },
  ],
  can_request: true,
  via_group: "Finance",
};

/** The owner's access plus exporting the log and changing org settings (SIEM). */
export const auditAdminAccess: MyAccessOut = {
  ...ownerAccess,
  control_plane_scopes: [...ownerAccess.control_plane_scopes, "audit:export", "settings:write"],
};

function exportJob(fields: Partial<ExportOut> & Pick<ExportOut, "id" | "status">): ExportOut {
  return {
    created_at: new Date().toISOString(),
    download_url: null,
    error: null,
    expires_at: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
    filters: {},
    format: "csv",
    row_count: null,
    size_bytes: null,
    ...fields,
  };
}

function matches(event: AuditEventOut, query: URLSearchParams): boolean {
  const action = query.get("action");
  const q = query.get("q")?.toLowerCase();
  const since = query.get("since");
  const until = query.get("until");
  return (
    (!query.get("actor") || event.actor.id === query.get("actor")) &&
    (!query.get("actor_kind") || event.actor.kind === query.get("actor_kind")) &&
    (!action ||
      (action.endsWith("*") ? event.action.startsWith(action.slice(0, -1)) : event.action === action)) &&
    (!query.get("decision") || event.decision === query.get("decision")) &&
    (!query.get("instance") || event.instance_id === query.get("instance")) &&
    (!query.get("resource") || event.resource_id === query.get("resource")) &&
    (!query.get("source") || event.source === query.get("source")) &&
    (!since || Date.parse(event.occurred_at) >= Date.parse(since)) &&
    (!until || Date.parse(event.occurred_at) < Date.parse(until)) &&
    (!q ||
      [event.resource_id, event.resource_display, event.request_id, event.ip, event.actor.display].some(
        (value) => value?.toLowerCase().includes(q),
      ))
  );
}

export type AuditRecorder = {
  /** Query strings sent to `GET /audit/events`. */
  eventQueries: string[];
  createdViews: unknown[];
  deletedViews: string[];
  grants: unknown[];
  requests: unknown[];
  explains: unknown[];
  exports: unknown[];
  /** Query strings sent to `GET /audit/export`. */
  downloads: string[];
};

/**
 * MSW handlers for the audit log with the 31 Oct sample; list them before `p01Handlers()` (they answer
 * `/me/access` with export and settings scopes, and `/audit/events` with the sample). Pass a recorder to see what
 * the page sent. Background exports finish on the second status check.
 */
export function auditGovernanceHandlers(recorder?: AuditRecorder) {
  let views = [...sampleAuditViews];
  const jobs = new Map<string, { job: ExportOut; polls: number }>();
  return [
    http.get(`${API}/me/access`, ({ request }) => {
      const instance = new URL(request.url).searchParams.get("instance");
      return HttpResponse.json(
        instance
          ? {
              ...auditAdminAccess,
              instance_id: instance,
              roles: ["Full access"],
              token_scopes: ["agent_os:admin"],
              runtime_scopes: ["agent_os:admin"],
            }
          : auditAdminAccess,
      );
    }),
    http.get(`${API}/audit/events`, ({ request }) => {
      const url = new URL(request.url);
      recorder?.eventQueries.push(url.search);
      const rows = sampleAuditEvents.filter((event) => matches(event, url.searchParams));
      return HttpResponse.json({ data: rows, next_cursor: null });
    }),
    http.get(`${API}/audit/events/:id`, ({ params }) => {
      const found = sampleAuditEvents.find((event) => event.id === params.id);
      return found
        ? HttpResponse.json(found)
        : HttpResponse.json(
            { code: "not_found", status: 404, title: "Not found", type: "x" },
            { status: 404 },
          );
    }),
    http.get(`${API}/audit/actors`, () => HttpResponse.json(sampleAuditActors)),
    http.get(`${API}/audit/actions`, () => HttpResponse.json(sampleAuditActions)),
    http.get(`${API}/audit/policy`, () => HttpResponse.json(sampleAuditPolicy)),
    http.get(`${API}/audit/stream-status`, () => HttpResponse.json(sampleStreamStatus())),
    http.get(`${API}/audit/views`, () => HttpResponse.json(views)),
    http.post(`${API}/audit/views`, async ({ request }) => {
      const body = (await request.json()) as {
        name: string;
        filters?: Record<string, string>;
        shared?: boolean;
      };
      recorder?.createdViews.push(body);
      const created = savedView({
        id: `vw_${String(views.length + 1)}`,
        name: body.name,
        filters: body.filters ?? {},
        count: 1,
        position: views.length,
        shared: body.shared ?? false,
        owner_id: body.shared ? null : DANIEL,
      });
      views = [...views, created];
      return HttpResponse.json(created, { status: 201 });
    }),
    http.delete(`${API}/audit/views/:id`, ({ params }) => {
      recorder?.deletedViews.push(String(params.id));
      views = views.filter((view) => view.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(`${API}/audit/export`, ({ request }) => {
      const url = new URL(request.url);
      recorder?.downloads.push(url.search);
      const format = url.searchParams.get("format") ?? "csv";
      return new HttpResponse("id,occurred_at,action\n", {
        headers: {
          "Content-Type": format === "jsonl" ? "application/x-ndjson" : "text/csv",
          "Content-Disposition": `attachment; filename="audit-2026-10-31.${format}"`,
        },
      });
    }),
    http.post(`${API}/audit/exports`, async ({ request }) => {
      const body = (await request.json()) as { format?: "csv" | "jsonl"; filters?: Record<string, string> };
      recorder?.exports.push(body);
      const job = exportJob({
        id: `exp_${String(jobs.size + 1)}`,
        status: "queued",
        format: body.format ?? "csv",
        filters: body.filters ?? {},
      });
      jobs.set(job.id, { job, polls: 0 });
      return HttpResponse.json(job, { status: 202 });
    }),
    http.get(`${API}/audit/exports`, () => HttpResponse.json([...jobs.values()].map((entry) => entry.job))),
    http.get(`${API}/audit/exports/:id`, ({ params }) => {
      const entry = jobs.get(String(params.id));
      if (!entry)
        return HttpResponse.json(
          { code: "not_found", status: 404, title: "Not found", type: "x" },
          { status: 404 },
        );
      entry.polls += 1;
      entry.job =
        entry.polls === 1
          ? { ...entry.job, status: "running" }
          : {
              ...entry.job,
              status: "done",
              row_count: 48_210,
              size_bytes: 3_400_000,
              download_url: `/api/v1/audit/exports/${entry.job.id}/download`,
            };
      return HttpResponse.json(entry.job);
    }),
    http.post(`${API}/audit/verify`, () =>
      HttpResponse.json({ ok: true, checked: sampleAuditEvents.length, first_broken_event_id: null }),
    ),
    http.post(`${API}/access/explain`, async ({ request }) => {
      const body = (await request.json()) as { user_id: string; scope?: string };
      recorder?.explains.push(body);
      return HttpResponse.json(
        body.user_id === JONAS
          ? sampleJonasExplanation
          : { ...sampleJonasExplanation, explanation: `Needs ${body.scope ?? "a scope"}.`, alternatives: [] },
      );
    }),
    http.post(`${API}/access/temporary`, async ({ request }) => {
      const body = (await request.json()) as {
        principal_id: string;
        instance?: string | null;
        scopes?: string[];
        reason: string;
        duration_hours: number;
      };
      recorder?.grants.push(body);
      const binding: BindingOut = {
        id: "bnd_temp_1",
        principal_id: body.principal_id,
        principal_kind: "user",
        instance_id: body.instance ?? null,
        role_id: null,
        scopes: body.scopes ?? [],
        reason: body.reason,
        created_at: new Date().toISOString(),
        created_by: DANIEL,
        expires_at: new Date(Date.now() + body.duration_hours * 3600 * 1000).toISOString(),
      };
      return HttpResponse.json(binding, { status: 201 });
    }),
    http.post(`${API}/access/requests`, async ({ request }) => {
      const body = (await request.json()) as {
        instance?: string | null;
        scopes?: string[];
        reason: string;
        duration_hours?: number;
      };
      recorder?.requests.push(body);
      const created: AccessRequestOut = {
        id: "req_access_1",
        requester_id: DANIEL,
        instance_id: body.instance ?? null,
        role_id: null,
        scopes: body.scopes ?? [],
        reason: body.reason,
        duration_hours: body.duration_hours ?? 4,
        status: "pending",
        binding_id: null,
        created_at: new Date().toISOString(),
        decided_at: null,
        decided_by: null,
        expires_at: null,
        note: null,
      };
      return HttpResponse.json(created, { status: 201 });
    }),
  ];
}

export function auditRecorder(): AuditRecorder {
  return {
    eventQueries: [],
    createdViews: [],
    deletedViews: [],
    grants: [],
    requests: [],
    explains: [],
    exports: [],
    downloads: [],
  };
}
