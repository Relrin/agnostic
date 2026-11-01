import { releaseRun, runRegistry } from "@agnostic/core";
import { API, GATEWAY, p01Handlers, p02Handlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ChatPage as Page } from "./chat-page";

/** Tooltips need the provider the shell mounts. */
function ChatPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...p01Handlers(), ...p02Handlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...handlers());
  sessionStorage.clear();
  for (const key of Object.keys(runRegistry.getState().streams)) releaseRun(key);
});
afterAll(() => {
  server.close();
});

const SESSION_URL = "/i/prod-agentos/chat/agents/support-triage/ses_7f3a91c2";
const PATH = "/i/$instance/chat/$kind/$componentId/$sessionId";

describe("ChatPage", () => {
  it("shows the session list, the paused run and an inline approval", async () => {
    renderPage(ChatPage, { path: PATH, url: SESSION_URL });
    const sessions = await screen.findByRole("navigation", { name: "Sessions for support-triage" });
    expect(within(sessions).getByText("Refund for order 4471")).toBeInTheDocument();

    const run = await screen.findByRole("article", { name: "Run run_9f2c41" });
    expect(within(run).getByText("PAUSED")).toBeInTheDocument();
    expect(within(run).getAllByText("refund_customer").length).toBeGreaterThan(0);
    expect(screen.getByText("Please refund 49 for cus_8812")).toBeInTheDocument();

    const approval = await screen.findByRole("region", { name: "Approval required for refund_customer" });
    expect(within(approval).getByLabelText("tool_args")).toHaveTextContent('"amount": 49');
    expect(within(approval).getByText(/Shown because you hold/)).toHaveTextContent(
      "approvals:write on prod-agentos",
    );
    expect(screen.getByRole("textbox", { name: "Message Support triage" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mention member" })).toBeDisabled();
  });

  it("approves with edited arguments through the control plane, then streams the continuation", async () => {
    const decisions: unknown[] = [];
    const resumes: string[] = [];
    const run = { run_id: "run_9f2c41", session_id: "ses_7f3a91c2", agent_id: "support-triage" };
    const replay = [
      { event: "RunStarted", event_index: 0, ...run },
      {
        event: "RunPaused",
        event_index: 1,
        ...run,
        tools: [{ tool_call_id: "call_refund", tool_name: "refund_customer" }],
      },
      { event: "RunContinued", event_index: 2, ...run },
      { event: "RunContent", event_index: 3, ...run, content: "Refunded 45.00 to cus_8812." },
      { event: "RunCompleted", event_index: 4, ...run },
    ]
      .map(
        (event) => `event: ${event.event}
data: ${JSON.stringify(event)}

`,
      )
      .join("");
    server.use(
      http.post(`${API}/instances/:instance/approvals/:approval/decide`, async ({ request }) => {
        decisions.push(await request.json());
        return HttpResponse.json({
          approval_id: "apr_1",
          instance_id: "ins_x",
          decision: "approve",
          status: "approved",
          run_id: "run_9f2c41",
          session_id: "ses_7f3a91c2",
          continue_state: "continued",
          continue_detail: null,
          already_resolved: false,
          args_changed: ["amount"],
        });
      }),
      // The run continued in the background: the page replays it from the start through /resume.
      http.post(`${GATEWAY}/agents/:agent/runs/:run/resume`, async ({ request }) => {
        resumes.push(await request.text());
        return new HttpResponse(replay, { headers: { "Content-Type": "text/event-stream" } });
      }),
    );
    const user = userEvent.setup();
    renderPage(ChatPage, { path: PATH, url: SESSION_URL });
    const approval = await screen.findByRole("region", { name: "Approval required for refund_customer" });
    await user.click(within(approval).getByRole("button", { name: "Edit args" }));
    const editor = within(approval).getByLabelText("tool_args (JSON)");
    await user.clear(editor);
    await user.click(editor);
    await user.paste('{"customer_id": "cus_8812", "amount": 45, "reason": "requested in chat"}');
    await user.click(within(approval).getByRole("button", { name: "Approve with edits" }));
    expect(await screen.findByText("Refunded 45.00 to cus_8812.")).toBeInTheDocument();
    expect(
      within(screen.getByRole("article", { name: "Run run_9f2c41" })).getByText("COMPLETED"),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(resumes).toEqual(["session_id=ses_7f3a91c2"]);
    });
    expect(decisions).toEqual([
      {
        decision: "approve",
        edited_args: { customer_id: "cus_8812", amount: 45, reason: "requested in chat" },
      },
    ]);
  });

  it("explains when the person can't decide", async () => {
    server.use(
      http.get(`${API}/me/access`, () =>
        HttpResponse.json({
          user_id: "usr_viewer",
          instance_id: "ins_x",
          org_role: "member",
          roles: ["Viewer"],
          token_scopes: ["agents:read", "sessions:read", "approvals:read"],
          runtime_scopes: ["agents:read", "sessions:read", "approvals:read"],
          control_plane_scopes: ["org:read", "os:read"],
          grants: [],
        }),
      ),
    );
    renderPage(ChatPage, { path: PATH, url: SESSION_URL });
    const approval = await screen.findByRole("region", { name: "Approval required for refund_customer" });
    expect(
      within(approval).getByText("Waiting for someone with approvals:write on prod-agentos."),
    ).toBeInTheDocument();
    expect(within(approval).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });
});
