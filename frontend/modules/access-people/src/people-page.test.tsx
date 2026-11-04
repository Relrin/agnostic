import {
  API,
  PEOPLE,
  PEOPLE_GROUPS,
  PROD,
  sampleOrgHandlers,
  peopleGroupsHandlers,
  renderPage,
  sampleOrg,
} from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { PeoplePage as Page } from "./people-page";

/** Tooltips need the provider the shell mounts. */
function PeoplePage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

// People & groups handlers go first: they extend the base sample org's members, bindings and invitations.
const handlers = () => [...peopleGroupsHandlers(), ...sampleOrgHandlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  // jsdom has no pointer capture or layout; Radix selects ask for both.
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => undefined;
  Element.prototype.releasePointerCapture = () => undefined;
  Element.prototype.scrollIntoView = () => undefined;
});
afterEach(() => {
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

const PATH = "/access/people";

/** Records the JSON bodies posted to `path`, answering with what `reply` returns. */
function capture(method: "post" | "put", path: string, reply: (body: unknown) => unknown, status = 200) {
  const sent: unknown[] = [];
  server.use(
    http[method](`${API}${path}`, async ({ request }) => {
      const body = await request.json();
      sent.push(body);
      return HttpResponse.json(reply(body) as Record<string, unknown>, { status });
    }),
  );
  return sent;
}

async function choose(user: ReturnType<typeof userEvent.setup>, trigger: HTMLElement, option: string) {
  await user.click(trigger);
  await user.click(await screen.findByRole("option", { name: option }));
}

async function row(name: string): Promise<HTMLElement> {
  const table = await screen.findByRole("table", { name: "Members" });
  const cell = await within(table).findByRole("button", { name });
  const tr = cell.closest("tr");
  if (!tr) throw new Error(`${name}'s row is missing`);
  return tr;
}

describe("PeoplePage", () => {
  it("shows each member's access by instance, through groups or direct", async () => {
    renderPage(PeoplePage, { path: PATH });
    const maya = await row("Maya Chen");
    expect(within(maya).getAllByText("via Support AI")).toHaveLength(2);
    expect(within(maya).getAllByText("via Billing ops")).toHaveLength(2);
    expect(within(maya).getByText("agents:billing-agent:run")).toBeInTheDocument();
    expect(within(maya).getByText("Support AI, Billing ops")).toBeInTheDocument();
    const daniel = await row("Daniel Okafor");
    expect(within(daniel).getByText("Full access")).toBeInTheDocument();
    const lena = await row("Lena Ito");
    expect(within(lena).getByText("ends 30 Nov")).toBeInTheDocument();
    const aiko = await row("Aiko Tan");
    expect(within(aiko).getByText("all")).toBeInTheDocument();
    expect(within(aiko).getByText("Direct")).toBeInTheDocument();

    expect(await screen.findByText("Okta SCIM · synced 4 min ago")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /Groups/ })).toHaveTextContent("5");
    });
    expect(screen.getByRole("tab", { name: /Members/ })).toHaveTextContent("9");
    expect(screen.getByRole("tab", { name: /Invitations/ })).toHaveTextContent("2");
    expect(screen.getByRole("tab", { name: /Requests/ })).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      expect.stringMatching(/\/api\/v1\/members\/export\.csv$/),
    );
  });

  it("filters members by group from the URL", async () => {
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?in_group=${PEOPLE_GROUPS.billing}` });
    const table = await screen.findByRole("table", { name: "Members" });
    await within(table).findByRole("button", { name: "Omar Haddad" });
    expect(within(table).getByRole("button", { name: "Maya Chen" })).toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: "Priya Nair" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Group: Billing ops" })).toBeInTheDocument();
  });

  it("adds the selected members to a group in bulk", async () => {
    const sent = capture("post", "/members/bulk", (body) =>
      (body as { user_ids: string[] }).user_ids.map((id) => ({ user_id: id, ok: true, error: null })),
    );
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: PATH });
    await row("Priya Nair");
    await user.click(screen.getByLabelText("Select Priya Nair"));
    await user.click(screen.getByLabelText("Select Lena Ito"));
    const bar = screen.getByRole("region", { name: "Bulk actions" });
    expect(within(bar).getByText("2 selected")).toBeInTheDocument();
    await choose(user, within(bar).getByRole("combobox", { name: "Add to group" }), "Research");
    await waitFor(() => {
      expect(sent).toEqual([
        {
          user_ids: [PEOPLE.priya, PEOPLE.lena],
          operation: "add_to_group",
          group_id: PEOPLE_GROUPS.research,
        },
      ]);
    });
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Bulk actions" })).not.toBeInTheDocument();
    });
  });

  it("opens a member with access by instance and adds a direct grant of scopes that expires", async () => {
    const sent = capture(
      "post",
      "/access/bindings",
      () => ({
        id: "bnd_new",
        principal_kind: "user",
        principal_id: PEOPLE.maya,
        instance_id: PROD,
        role_id: null,
        scopes: ["agents:billing-agent:run"],
        expires_at: "2026-11-30T23:59:59Z",
        reason: "Refund backlog",
        created_by: PEOPLE.daniel,
        created_at: "2026-11-03T09:00:00Z",
      }),
      201,
    );
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?member=${PEOPLE.maya}` });
    const aside = await screen.findByRole("dialog", { name: "Maya Chen" });
    const prod = within(aside).getByRole("listitem", { name: "Access on prod-agentos" });
    expect(within(prod).getAllByRole("button", { name: "Support AI" })).toHaveLength(1);
    expect(within(prod).getAllByRole("button", { name: "Billing ops" })).toHaveLength(2);
    expect(within(aside).getByText(/User isolation is on for prod-agentos/)).toBeInTheDocument();

    await user.click(within(aside).getByRole("button", { name: "Add direct role" }));
    const form = within(aside).getByRole("form", { name: "Add direct role" });
    await user.click(within(form).getByRole("radio", { name: "Scopes" }));
    await user.click(await within(form).findByLabelText("agents:run"));
    await user.type(within(form).getByLabelText("Only for"), "billing-agent");
    await user.type(within(form).getByLabelText("Expires (optional)"), "2026-11-30");
    await user.type(within(form).getByLabelText("Reason (optional)"), "Refund backlog");
    await user.click(within(form).getByRole("button", { name: "Add" }));
    await waitFor(() => {
      expect(sent).toEqual([
        {
          principal_kind: "user",
          principal_id: PEOPLE.maya,
          role_id: null,
          scopes: ["agents:billing-agent:run"],
          instance: PROD,
          expires_at: new Date("2026-11-30T23:59:59").toISOString(),
          reason: "Refund backlog",
        },
      ]);
    });
  });

  it("checks a permission with action, resource, component and instance", async () => {
    const sent = capture("post", "/access/explain", () => ({
      allowed: true,
      scope: "agents:billing-agent:run",
      instance_id: PROD,
      granted_by: [],
      missing_scopes: [],
      alternatives: [],
      explanation: "Granted by Billing ops via Billing ops → `agents:billing-agent:run` on prod-agentos.",
      via_group: "Billing ops",
    }));
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?member=${PEOPLE.maya}` });
    const aside = await screen.findByRole("dialog", { name: "Maya Chen" });
    await choose(user, within(aside).getByRole("combobox", { name: "Resource" }), "agents");
    await choose(user, within(aside).getByRole("combobox", { name: "Action" }), "run");
    await user.type(within(aside).getByLabelText("Agent id"), "billing-agent");
    await user.click(within(aside).getByRole("button", { name: "Check" }));
    const answer = await within(aside).findByRole("status");
    expect(within(answer).getByLabelText("Allowed")).toBeInTheDocument();
    expect(answer).toHaveTextContent(
      "Yes. Granted by Billing ops via Billing ops → agents:billing-agent:run on prod-agentos.",
    );
    expect(sent).toEqual([
      { user_id: PEOPLE.maya, resource: "agents", verb: "run", component: "billing-agent", instance: PROD },
    ]);
  });

  it("creates a group with members and owners", async () => {
    const sent = capture(
      "post",
      "/directory/groups",
      (body) => ({
        id: "grp_oncall",
        name: (body as { name: string }).name,
        description: "",
        source: "manual",
        external_id: null,
        external_name: null,
        sync_label: "Manual",
        synced: false,
        member_count: 2,
        created_at: "2026-11-03T09:00:00Z",
        updated_at: "2026-11-03T09:00:00Z",
        members: [],
      }),
      201,
    );
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?tab=groups` });
    const table = await screen.findByRole("table", { name: "Groups" });
    expect(within(table).getByText("SCIM · support-ai")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New group" }));
    const dialog = await screen.findByRole("dialog", { name: "New group" });
    await user.type(within(dialog).getByLabelText("Name"), "On-call");
    await user.type(within(dialog).getByLabelText("Description"), "Pages for prod");
    await user.click(within(dialog).getByRole("checkbox", { name: "Priya Nair" }));
    await user.click(within(dialog).getByRole("checkbox", { name: "Lena Ito" }));
    await user.click(within(dialog).getByLabelText("Lena Ito is an owner"));
    await user.click(within(dialog).getByRole("button", { name: "Create group" }));
    await waitFor(() => {
      expect(sent).toEqual([
        {
          name: "On-call",
          description: "Pages for prod",
          member_ids: [PEOPLE.priya],
          owner_ids: [PEOPLE.lena],
        },
      ]);
    });
  });

  it("opens a synced group with its bindings, approval routes and owners", async () => {
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?tab=groups&group=${PEOPLE_GROUPS.support}` });
    const aside = await screen.findByRole("dialog", { name: "Support AI" });
    expect(within(aside).getByText(/synced from support-ai/)).toBeInTheDocument();
    const bindings = within(aside).getByRole("list", { name: "Role bindings" });
    expect(within(bindings).getByText("Operator")).toBeInTheDocument();
    expect(within(bindings).getByText("Builder")).toBeInTheDocument();
    const routes = await within(aside).findByRole("list", { name: "Approval routes" });
    expect(within(routes).getByText("refund_customer")).toBeInTheDocument();
    expect(
      within(routes).getByText(/on prod-agentos · support-triage and billing-agent/),
    ).toBeInTheDocument();
    const members = within(aside).getByRole("list", { name: "Group members" });
    const maya = within(members).getByText("Maya Chen").closest("li");
    if (!maya) throw new Error("Maya is missing from the group");
    expect(within(maya).getByText("owner")).toBeInTheDocument();
    expect(within(aside).getByText(/Membership comes from the IdP/)).toBeInTheDocument();
    expect(within(aside).queryByRole("button", { name: /Remove Maya Chen/ })).not.toBeInTheDocument();
  });

  it("approves a pending access request with a note", async () => {
    const sent = capture("post", "/access/requests/:request/approve", () => ({
      id: "req_omar_builder",
      requester_id: PEOPLE.omar,
      instance_id: PROD,
      role_id: "rol_builder",
      scopes: [],
      duration_hours: 8,
      reason: "Fix the refund prompt before Friday's release",
      status: "approved",
      note: "Until Friday",
      binding_id: "bnd_tmp",
      decided_at: "2026-11-03T09:00:00Z",
      decided_by: PEOPLE.daniel,
      expires_at: "2026-11-03T17:00:00Z",
      can_decide: false,
      created_at: "2026-11-03T08:30:00Z",
    }));
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?tab=requests` });
    const table = await screen.findByRole("table", { name: "Access requests" });
    expect(within(table).getByText("Fix the refund prompt before Friday's release")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Cancel request" })).toBeInTheDocument();
    await user.click(within(table).getByRole("button", { name: "Approve Omar Haddad's request" }));
    const dialog = await screen.findByRole("dialog", { name: "Approve Omar Haddad's request?" });
    await user.type(within(dialog).getByLabelText("Note (optional)"), "Until Friday");
    await user.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(sent).toEqual([{ note: "Until Friday" }]);
    });
  });

  it("invites someone into groups and shows the link to share", async () => {
    const sent = capture(
      "post",
      "/invitations",
      () => ({
        invitation: {
          id: "inv_1",
          email: "rui@localhost.company",
          org_role: "member",
          bindings: [],
          group_ids: [PEOPLE_GROUPS.research],
          access_ends_at: null,
          invited_by: PEOPLE.daniel,
          expires_at: "2026-11-10T09:00:00Z",
          status: "pending",
          created_at: "2026-11-03T09:00:00Z",
        },
        accept_url: "http://agnostic.test/invite/tok",
        email_sent: true,
      }),
      201,
    );
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?tab=invitations` });
    const list = await screen.findByRole("list", { name: "Invitations" });
    expect(within(list).getByText(/Operator on prod-agentos · joins Billing ops/)).toBeInTheDocument();
    expect(within(list).getByText(/Viewer on staging-agentos · access ends 30 Nov/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Invite people" }));
    const dialog = await screen.findByRole("dialog", { name: "Invite people" });
    await user.type(within(dialog).getByLabelText("Email"), "rui@localhost.company");
    await user.click(within(dialog).getByRole("checkbox", { name: "Research" }));
    await user.click(within(dialog).getByRole("button", { name: "Send invitation" }));
    expect(await screen.findByText("http://agnostic.test/invite/tok")).toBeInTheDocument();
    expect(screen.getByText("Invited rui@localhost.company")).toBeInTheDocument();
    expect(sent).toEqual([
      {
        email: "rui@localhost.company",
        org_role: "member",
        bindings: [],
        group_ids: [PEOPLE_GROUPS.research],
        access_ends_at: null,
        delivery: "email",
      },
    ]);
  });

  it("creates an invitation link without sending an email", async () => {
    const sent = capture(
      "post",
      "/invitations",
      () => ({ invitation: issuedInvitation("rui@localhost.company"), accept_url: LINK, email_sent: false }),
      201,
    );
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?tab=invitations` });
    await user.click(await screen.findByRole("button", { name: "Invite people" }));
    const dialog = await screen.findByRole("dialog", { name: "Invite people" });
    await user.type(within(dialog).getByLabelText("Email"), "rui@localhost.company");
    await user.click(within(dialog).getByRole("radio", { name: /Create link only/ }));
    await user.click(within(dialog).getByRole("button", { name: "Create link" }));
    expect(await screen.findByText(LINK)).toBeInTheDocument();
    expect(screen.getByText("Invitation link for rui@localhost.company")).toBeInTheDocument();
    expect(sent).toEqual([expect.objectContaining({ email: "rui@localhost.company", delivery: "link" })]);
  });

  it("copies a new link for a pending invitation after confirming", async () => {
    const renewed: string[] = [];
    server.use(
      http.post(`${API}/invitations/:id/link`, ({ params }) => {
        renewed.push(String(params.id));
        return HttpResponse.json({
          invitation: issuedInvitation("rafael@localhost.company"),
          accept_url: LINK,
          email_sent: false,
        });
      }),
    );
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?tab=invitations` });
    const list = await screen.findByRole("list", { name: "Invitations" });
    const rafael = within(list).getByText("rafael@localhost.company").closest("li");
    if (!rafael) throw new Error("no invitation row for Rafael");
    await user.click(within(rafael).getByRole("button", { name: "Copy new link" }));
    const confirm = await screen.findByRole("dialog", { name: "Create a new invitation link?" });
    expect(
      within(confirm).getByText(/current link for rafael@localhost.company stops working/),
    ).toBeInTheDocument();
    await user.click(within(confirm).getByRole("button", { name: "Create new link" }));
    expect(await screen.findByText(LINK)).toBeInTheDocument();
    expect(renewed).toEqual(["inv_01M6A0EEZEQ373S26F2014RAFA"]);
  });

  it("offers only links when email isn't configured", async () => {
    server.use(http.get(`${API}/org`, () => HttpResponse.json({ ...sampleOrg, email_delivery: false })));
    const user = userEvent.setup();
    renderPage(PeoplePage, { path: PATH, url: `${PATH}?tab=invitations` });
    const list = await screen.findByRole("list", { name: "Invitations" });
    await waitFor(() => {
      expect(within(list).queryByRole("button", { name: "Resend" })).not.toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "Invite people" }));
    const dialog = await screen.findByRole("dialog", { name: "Invite people" });
    expect(within(dialog).queryByRole("radio")).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Create link" })).toBeInTheDocument();
  });
});

const LINK = "http://agnostic.test/invite/new-token";

function issuedInvitation(email: string) {
  return {
    id: "inv_1",
    email,
    org_role: "member",
    bindings: [],
    group_ids: [],
    access_ends_at: null,
    invited_by: PEOPLE.daniel,
    expires_at: "2026-11-10T09:00:00Z",
    status: "pending",
    created_at: "2026-11-03T09:00:00Z",
  };
}
