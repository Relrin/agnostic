import { API, approvalsHandlers, sampleOrgHandlers, operateHandlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ApprovalsPage as Page } from "./approvals-page";

/** Tooltips need the provider the shell mounts. */
function ApprovalsPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

// The approvals handlers go first: the operate handlers have a simpler decide handler for the chat page.
const handlers = () => [...approvalsHandlers(), ...sampleOrgHandlers(), ...operateHandlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  // jsdom has no layout: the Slack deep link scrolls the decision into view.
  Element.prototype.scrollIntoView = () => undefined;
});
afterEach(() => {
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

const PATH = "/i/$instance/approvals";

/** Records the bodies sent to decide, answering like the control plane. */
function captureDecisions(): unknown[] {
  const sent: unknown[] = [];
  server.use(
    http.post(`${API}/instances/:instance/approvals/:approval/decide`, async ({ request, params }) => {
      const body = (await request.json()) as { decision: string; edited_args?: Record<string, unknown> };
      sent.push(body);
      return HttpResponse.json({
        approval_id: String(params.approval),
        instance_id: "ins_prod",
        decision: body.decision,
        status: body.decision === "approve" ? "approved" : "rejected",
        run_id: "run_4471a",
        session_id: "ses_4471a",
        continue_state: "continued",
        continue_detail: null,
        already_resolved: false,
        args_changed: body.edited_args ? ["amount"] : [],
      });
    }),
  );
  return sent;
}

describe("ApprovalsPage", () => {
  it("shows status tabs with counts and the pending inbox", async () => {
    renderPage(ApprovalsPage, { path: PATH, url: "/i/prod-agentos/approvals" });
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /Pending/ })).toHaveTextContent("3");
    });
    expect(screen.getByRole("tab", { name: /Approved/ })).toHaveTextContent("41");
    expect(screen.getByRole("tab", { name: /Rejected/ })).toHaveTextContent("6");
    const table = await screen.findByRole("table", { name: "Approvals" });
    expect(within(table).getByText("blocking · apv_7Kq2")).toBeInTheDocument();
    expect(within(table).getByText("zd:48121")).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Expires" })).toBeInTheDocument();
    expect(screen.getByText(/^3 waiting · oldest 2h 1[34]m$/)).toBeInTheDocument();
  });

  it("filters by tool from the URL and switches tabs", async () => {
    const user = userEvent.setup();
    renderPage(ApprovalsPage, { path: PATH, url: "/i/prod-agentos/approvals?tool=apply_account_credit" });
    const table = await screen.findByRole("table", { name: "Approvals" });
    await waitFor(() => {
      expect(within(table).queryByText("blocking · apv_7Kq2")).not.toBeInTheDocument();
    });
    expect(within(table).getByText("blocking · apv_7Kp4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tool: apply_account_credit" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.click(screen.getByRole("tab", { name: /Rejected/ }));
    expect(await screen.findByText("blocking · apv_7Hk3")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Resolved" })).toBeInTheDocument();
    expect(screen.getByText(/Omar Haddad · /)).toBeInTheDocument();
  });

  it("opens an approval with its context and timeline", async () => {
    const user = userEvent.setup();
    renderPage(ApprovalsPage, { path: PATH, url: "/i/prod-agentos/approvals" });
    await user.click(await screen.findByText("blocking · apv_7Kq2"));
    const aside = await screen.findByRole("complementary", { name: "Approval details" });
    expect(await within(aside).findByRole("heading", { name: "refund_customer" })).toBeInTheDocument();
    expect(within(aside).getByText("RUN PAUSED")).toBeInTheDocument();
    expect(within(aside).getByText(/My card was charged twice for order #4471/)).toBeInTheDocument();
    expect(within(aside).getByText(/Refunding the duplicate charge/)).toBeInTheDocument();
    const timeline = within(aside).getByRole("list", { name: "Approval timeline" });
    expect(within(timeline).getByText("Viewed by Maya Chen")).toBeInTheDocument();
    expect(within(timeline).getByText("Waiting for a decision")).toBeInTheDocument();
    expect(within(aside).getByRole("link", { name: /Open session/ })).toHaveAttribute(
      "href",
      "/i/prod-agentos/sessions/ses_4471a",
    );
    expect(within(aside).getByText("You resolve as Daniel Okafor.", { exact: false })).toBeInTheDocument();
  });

  it("needs a note to reject and sends it", async () => {
    const user = userEvent.setup();
    const sent = captureDecisions();
    renderPage(ApprovalsPage, { path: PATH, url: "/i/prod-agentos/approvals?approval=apv_7Kq2" });
    const aside = await screen.findByRole("complementary", { name: "Approval details" });
    const reject = await within(aside).findByRole("button", { name: "Reject" });
    expect(reject).toBeDisabled();
    await user.type(within(aside).getByLabelText("Note · required to reject"), "Outside the refund window.");
    expect(reject).toBeEnabled();
    await user.click(reject);
    await waitFor(() => {
      expect(sent).toEqual([{ decision: "reject", note: "Outside the refund window." }]);
    });
    expect(await within(aside).findByText("Rejected · the run is continuing.")).toBeInTheDocument();
  });

  it("approves with edited arguments and shows the diff", async () => {
    const user = userEvent.setup();
    const sent = captureDecisions();
    renderPage(ApprovalsPage, { path: PATH, url: "/i/prod-agentos/approvals?approval=apv_7Kq2" });
    const aside = await screen.findByRole("complementary", { name: "Approval details" });
    const toggle = await within(aside).findByRole("button", { name: "Edit before approving" });
    await user.click(toggle);
    expect(within(aside).getByRole("button", { name: "Done editing" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const amount = within(aside).getByLabelText("amount");
    await user.clear(amount);
    await user.type(amount, "45");
    const diff = within(aside).getByRole("definition");
    expect(diff).toHaveTextContent("49");
    expect(diff).toHaveTextContent("45");
    await user.click(within(aside).getByRole("button", { name: "Approve & continue run" }));
    await waitFor(() => {
      expect(sent).toEqual([
        {
          decision: "approve",
          edited_args: {
            order_id: "4471",
            charge_id: "ch_3PqL9w",
            amount: 45,
            currency: "USD",
            reason: "duplicate_charge",
          },
        },
      ]);
    });
    expect(
      await within(aside).findByText("Approved with edited amount · the run is continuing."),
    ).toBeInTheDocument();
  });

  it("focuses the decision from a Slack link without submitting it", async () => {
    const sent = captureDecisions();
    renderPage(ApprovalsPage, {
      path: PATH,
      url: "/i/prod-agentos/approvals?approval=apv_7Kq2&intent=reject",
    });
    const aside = await screen.findByRole("complementary", { name: "Approval details" });
    const note = await within(aside).findByLabelText("Note · required to reject");
    await waitFor(() => {
      expect(note).toHaveFocus();
    });
    expect(sent).toEqual([]);
  });

  it("explains why an audit approval can't be resolved and shows resolved records", async () => {
    renderPage(ApprovalsPage, {
      path: PATH,
      url: "/i/prod-agentos/approvals?status=rejected&approval=apv_7Hk3",
    });
    const aside = await screen.findByRole("complementary", { name: "Approval details" });
    const resolution = await within(aside).findByRole("group", { name: "Resolution" });
    expect(within(resolution).getByText("Rejected by Omar Haddad")).toBeInTheDocument();
    expect(within(resolution).getByText(/Outside the 30-day refund window/)).toBeInTheDocument();
    expect(within(aside).queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("turns Slack notifications on for new approvals", async () => {
    const user = userEvent.setup();
    let sent: unknown;
    server.use(
      http.put(`${API}/me/notification-preferences`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({
          slack_available: true,
          quiet_hours: null,
          events: [
            {
              event: {
                name: "approval.created",
                label: "Approval requested",
                description: "",
                defaults: ["in_app"],
              },
              channels: ["in_app", "slack"],
              custom: true,
            },
          ],
        });
      }),
    );
    renderPage(ApprovalsPage, { path: PATH, url: "/i/prod-agentos/approvals" });
    const toggle = await screen.findByRole("switch", { name: "Notify me in Slack" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await user.click(toggle);
    await waitFor(() => {
      expect(sent).toEqual({ events: { "approval.created": ["in_app", "slack"] } });
    });
    await waitFor(() => {
      expect(toggle).toHaveAttribute("aria-checked", "true");
    });
  });

  it("lists routing rules and adds one", async () => {
    const user = userEvent.setup();
    let sent: unknown;
    server.use(
      http.post(`${API}/instances/:instance/approvals/routes`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(
          {
            id: "rte_new",
            instance_id: "ins",
            name: "Escalations",
            tool_name: null,
            component_kind: null,
            component_ids: [],
            members: [{ id: "usr", name: "Marcus Chen" }],
            roles: [],
            channels: ["in_app"],
            channel_ids: [],
            created_by: null,
            updated_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
    );
    renderPage(ApprovalsPage, { path: PATH, url: "/i/prod-agentos/approvals" });
    await user.click(await screen.findByRole("button", { name: "Routing" }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText(/Routing is advisory/)).toBeInTheDocument();
    const routes = await within(sheet).findByRole("list", { name: "Routes" });
    expect(within(routes).getByText("Billing ops")).toBeInTheDocument();
    expect(within(routes).getByText("Support AI")).toBeInTheDocument();

    await user.click(within(sheet).getByRole("button", { name: "Add route" }));
    const form = within(sheet).getByRole("form", { name: "New route" });
    await user.type(within(form).getByLabelText("Route name"), "Escalations");
    await user.click(await within(form).findByRole("checkbox", { name: "Marcus Chen" }));
    await user.click(within(form).getByRole("button", { name: "Add route" }));
    await waitFor(() => {
      expect(sent).toMatchObject({
        name: "Escalations",
        tool_name: null,
        component_kind: null,
        member_ids: ["usr_01M6A0EEZEQ373S26F20142MAY"],
        role_ids: [],
        channels: ["in_app"],
        channel_ids: [],
      });
    });
  });
});
