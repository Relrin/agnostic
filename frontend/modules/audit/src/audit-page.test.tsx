import {
  API,
  AUDIT_MAYA_DENIAL,
  DANIEL,
  PROD,
  auditGovernanceHandlers,
  auditRecorder,
  ownerAccess,
  p01Handlers,
  renderPage,
  sampleAuditEvents,
  type AuditRecorder,
} from "@agnostic/testing";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { AuditPage } from "./audit-page";

let recorder: AuditRecorder = auditRecorder();
// The audit handlers go first: they answer /me/access with export rights and /audit/events with the sample.
const handlers = () => [...auditGovernanceHandlers(recorder), ...p01Handlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  recorder = auditRecorder();
  server.resetHandlers(...handlers());
  vi.restoreAllMocks();
});
afterAll(() => {
  server.close();
});

const PATH = "/access/audit";
const byAction = (action: string) => {
  const found = sampleAuditEvents.find((event) => event.action === action);
  if (!found) throw new Error(action);
  return found;
};

describe("AuditPage", () => {
  it("lists events with machine actors, where, decisions and retention", async () => {
    renderPage(AuditPage, { path: PATH });
    const table = await screen.findByRole("table", { name: "Audit events" });
    for (const header of ["UTC", "Actor", "Action", "Resource", "Where", "Decision"])
      expect(within(table).getByRole("columnheader", { name: header })).toBeInTheDocument();
    expect(within(table).getByText("17:04:12")).toBeInTheDocument();
    expect(within(table).getAllByText("sa:zendesk-bridge")[0]).toHaveClass("font-mono");
    expect(within(table).getByText("missing components:write")).toBeInTheDocument();
    expect(within(table).getAllByText("staging-agentos").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("DENIED")).toHaveLength(3);
    expect(await screen.findByText("Kept 400 days · append-only")).toBeInTheDocument();
    expect(screen.getByText("10 events · All events")).toBeInTheDocument();
  });

  it("shows the SIEM streaming pill linking to its settings", async () => {
    renderPage(AuditPage, { path: PATH });
    const pill = await screen.findByRole("link", {
      name: /^Streaming to SIEM · HTTPS webhook · last event \d s ago$/,
    });
    expect(pill).toHaveAttribute("href", "/org/settings/siem");
    expect(screen.getByRole("link", { name: "SIEM settings" })).toHaveAttribute("href", "/org/settings/siem");
  });

  it("hides the SIEM pill when nothing streams", async () => {
    server.use(
      http.get(`${API}/audit/stream-status`, () =>
        HttpResponse.json({ streaming: false, sinks: [], last_event_at: null }),
      ),
    );
    renderPage(AuditPage, { path: PATH });
    await screen.findByRole("table", { name: "Audit events" });
    expect(screen.queryByText(/Streaming to SIEM/)).not.toBeInTheDocument();
  });

  it("applies a saved view's filters", async () => {
    const user = userEvent.setup();
    renderPage(AuditPage, { path: PATH });
    const views = await screen.findByRole("group", { name: "Saved views" });
    const all = await within(views).findByRole("button", { name: "All events 10" });
    expect(all).toHaveAttribute("aria-pressed", "true");
    expect(within(views).getByRole("button", { name: "Role & permission changes 2" })).toBeInTheDocument();
    expect(within(views).getByRole("button", { name: "Approvals resolved 2" })).toBeInTheDocument();
    expect(within(views).getByRole("button", { name: "Service accounts 2" })).toBeInTheDocument();

    await user.click(within(views).getByRole("button", { name: "Denied in production 3" }));
    await waitFor(() => {
      expect(recorder.eventQueries.at(-1)).toContain("decision=denied");
    });
    expect(recorder.eventQueries.at(-1)).toContain(`instance=${PROD}`);
    expect(within(views).getByRole("button", { name: "Denied in production 3" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(await screen.findByText("3 events · Denied in production")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Decision: Denied" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Instance: prod-agentos" })).toBeInTheDocument();
  });

  it("saves the current filters as a shared view", async () => {
    const user = userEvent.setup();
    renderPage(AuditPage, { path: PATH, url: `${PATH}?decision=denied&source=agentos` });
    await user.click(await screen.findByRole("button", { name: "Save current filters" }));
    const dialog = await screen.findByRole("dialog", { name: "Save current filters" });
    expect(within(dialog).getByText("Decision: Denied · Source: AgentOS")).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Name"), "Agent denials");
    await user.click(
      within(dialog).getByRole("switch", { name: "Share with everyone who can read the log" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Save view" }));
    await waitFor(() => {
      expect(recorder.createdViews).toEqual([
        { name: "Agent denials", filters: { decision: "denied", source: "agentos" }, shared: true },
      ]);
    });
    const views = screen.getByRole("group", { name: "Saved views" });
    expect(await within(views).findByRole("button", { name: "Agent denials 1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("filters by an action prefix typed in the menu", async () => {
    const user = userEvent.setup();
    renderPage(AuditPage, { path: PATH });
    await screen.findByRole("table", { name: "Audit events" });
    await user.click(screen.getByRole("button", { name: "Action: Any" }));
    expect(await screen.findByRole("button", { name: /roles\.\*/ })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Action or prefix"), "components.*{Enter}");
    await waitFor(() => {
      expect(recorder.eventQueries.at(-1)).toContain("action=components.*");
    });
    expect(await screen.findByText("3 events · Filtered")).toBeInTheDocument();
  });

  it("draws the Operator role edit as a scope diff with a deep link", async () => {
    const event = byAction("roles.update");
    renderPage(AuditPage, { path: PATH, url: `${PATH}?event=${event.id}` });
    const aside = await screen.findByRole("complementary", { name: "Event details" });
    expect(await within(aside).findByRole("heading", { name: "roles.update" })).toBeInTheDocument();
    expect(within(aside).getByText("Changed the scopes of the Operator access role.")).toBeInTheDocument();
    const diff = within(aside).getByRole("list", { name: "Scopes" });
    const added = within(diff).getByText("knowledge:write").closest("li");
    const removed = within(diff).getByText("approvals:delete").closest("li");
    expect(added).toHaveTextContent("+Addedknowledge:write");
    expect(removed).toHaveTextContent("−Removedapprovals:delete");
    expect(within(diff).getByText("… 15 unchanged")).toBeInTheDocument();
    expect(
      within(aside).getByText("Applied to 9 people and 2 groups on their next request. No redeploy."),
    ).toBeInTheDocument();
    expect(within(aside).getByRole("link", { name: /Open role/ })).toHaveAttribute(
      "href",
      "/access/roles?role=rol_operator",
    );
    expect(within(aside).queryByText("Why it was denied")).not.toBeInTheDocument();
  });

  it("draws before/after diffs as changed arguments", async () => {
    const user = userEvent.setup();
    renderPage(AuditPage, { path: PATH });
    const table = await screen.findByRole("table", { name: "Audit events" });
    const row = within(table).getByText(
      "Approved a $49.00 refund on billing-agent. The run continued and completed.",
    );
    await user.click(row);
    const aside = await screen.findByRole("complementary", { name: "Event details" });
    expect(within(aside).getByLabelText("Changed arguments")).toHaveTextContent("status");
    expect(within(aside).getByRole("link", { name: /Open session ses_4471a/ })).toHaveAttribute(
      "href",
      "/i/prod-agentos/sessions/ses_4471a",
    );
  });

  it("explains a denial and grants temporary access", async () => {
    const user = userEvent.setup();
    const event = byAction("components.set_current");
    renderPage(AuditPage, { path: PATH, url: `${PATH}?event=${event.id}` });
    const aside = await screen.findByRole("complementary", { name: "Event details" });
    const why = await within(aside).findByRole("region", { name: "Why it was denied" });
    expect(within(why).getByText(AUDIT_MAYA_DENIAL)).toBeInTheDocument();
    expect(within(aside).getByText("403 Forbidden")).toBeInTheDocument();

    await user.click(await within(why).findByRole("button", { name: "Grant temporary access…" }));
    const dialog = await screen.findByRole("dialog", { name: "Grant temporary access" });
    expect(within(dialog).getByText("Maya Chen")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Scopes")).toHaveValue("components:write");
    const grant = within(dialog).getByRole("button", { name: "Grant access" });
    expect(grant).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Reason"), "Ship the v4 fix today");
    await user.click(grant);
    await waitFor(() => {
      expect(recorder.grants).toEqual([
        {
          principal_id: event.actor.id,
          instance: PROD,
          scopes: ["components:write"],
          reason: "Ship the v4 fix today",
          duration_hours: 4,
        },
      ]);
    });
  });

  it("asks the explain engine when a denial has no reason", async () => {
    const event = byAction("sessions.delete");
    renderPage(AuditPage, { path: PATH, url: `${PATH}?event=${event.id}` });
    const aside = await screen.findByRole("complementary", { name: "Event details" });
    expect(
      await within(aside).findByText(/Jonas has Viewer on prod-agentos \(via Finance\), which is read-only/),
    ).toBeInTheDocument();
    expect(within(aside).getByRole("list", { name: "Would be allowed with" })).toHaveTextContent(
      "Operator on prod-agentos",
    );
    expect(recorder.explains).toEqual([
      expect.objectContaining({ user_id: event.actor.id, scope: "sessions:delete", instance: PROD }),
    ]);
  });

  it("offers no grant for a scoped service account's denial", async () => {
    const event = byAction("approvals.resolve");
    renderPage(AuditPage, { path: PATH, url: `${PATH}?event=${event.id}` });
    const aside = await screen.findByRole("complementary", { name: "Event details" });
    expect(
      await within(aside).findByText(/Scoped service accounts can't resolve approvals/),
    ).toBeInTheDocument();
    expect(within(aside).queryByRole("button", { name: "Grant temporary access…" })).not.toBeInTheDocument();
    expect(within(aside).getByText("404 Not Found")).toBeInTheDocument();
  });

  it("lets the person who was denied request access", async () => {
    const user = userEvent.setup();
    const denied = {
      ...byAction("sessions.delete"),
      id: "evt_own",
      actor: { kind: "user", id: DANIEL, display: "Daniel Okafor" },
    };
    server.use(
      http.get(`${API}/me/access`, () =>
        HttpResponse.json({ ...ownerAccess, org_role: "member", control_plane_scopes: ["audit:read"] }),
      ),
      http.get(`${API}/audit/events`, () => HttpResponse.json({ data: [denied], next_cursor: null })),
    );
    renderPage(AuditPage, { path: PATH, url: `${PATH}?event=evt_own` });
    const aside = await screen.findByRole("complementary", { name: "Event details" });
    await user.click(await within(aside).findByRole("button", { name: "Request access" }));
    const dialog = await screen.findByRole("dialog", { name: "Request access" });
    await user.type(within(dialog).getByLabelText("Reason"), "Clean up test sessions");
    await user.click(within(dialog).getByRole("button", { name: "Send request" }));
    await waitFor(() => {
      expect(recorder.requests).toEqual([
        { instance: PROD, scopes: ["sessions:delete"], reason: "Clean up test sessions", duration_hours: 4 },
      ]);
    });
    expect(within(aside).queryByRole("button", { name: "Grant temporary access…" })).not.toBeInTheDocument();
  });

  it("downloads the current filters directly", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    Object.assign(URL, { createObjectURL: () => "blob:audit", revokeObjectURL: () => undefined });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(save);
    renderPage(AuditPage, { path: PATH, url: `${PATH}?decision=denied` });
    await user.click(await screen.findByRole("button", { name: "Export view" }));
    const dialog = await screen.findByRole("dialog", { name: "Export view" });
    await user.click(within(dialog).getByRole("radio", { name: "JSONL" }));
    const download = within(dialog).getByRole("link", { name: "Download JSONL" });
    expect(download).toHaveAttribute(
      "href",
      "http://agnostic.test/api/v1/audit/export?format=jsonl&decision=denied",
    );
    await user.click(download);
    await waitFor(() => {
      expect(recorder.downloads).toEqual(["?format=jsonl&decision=denied"]);
    });
    await waitFor(() => {
      expect(save).toHaveBeenCalled();
    });
  });

  it("runs a large export in the background", async () => {
    const user = userEvent.setup();
    server.use(
      http.get(`${API}/audit/export`, () =>
        HttpResponse.json(
          { code: "export_too_large", status: 413, title: "Too many events", type: "x" },
          { status: 413 },
        ),
      ),
    );
    renderPage(AuditPage, { path: PATH, url: `${PATH}?decision=denied` });
    await user.click(await screen.findByRole("button", { name: "Export view" }));
    const dialog = await screen.findByRole("dialog", { name: "Export view" });
    await user.click(within(dialog).getByRole("link", { name: "Download CSV" }));
    expect(await within(dialog).findByText("Too many events to download directly")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Run in background (large range)" }));
    await waitFor(() => {
      expect(recorder.exports).toEqual([{ format: "csv", filters: { decision: "denied" } }]);
    });
    const status = await within(dialog).findByRole("status", { name: "Background export" });
    expect(within(status).getByText("RUNNING")).toBeInTheDocument();
    const link = await within(status).findByRole("link", { name: "Download CSV" }, { timeout: 4000 });
    expect(link).toHaveAttribute("href", "http://agnostic.test/api/v1/audit/exports/exp_1/download");
    expect(within(status).getByText("48,210 events · 3.2 MB")).toBeInTheDocument();
  });

  it("hides export without audit:export", async () => {
    server.use(...p01Handlers());
    renderPage(AuditPage, { path: PATH });
    await screen.findByRole("table", { name: "Audit events" });
    expect(screen.queryByRole("button", { name: "Export view" })).not.toBeInTheDocument();
  });
});
