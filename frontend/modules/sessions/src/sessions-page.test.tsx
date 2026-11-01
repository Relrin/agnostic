import { GATEWAY, p01Handlers, p02Handlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { runNote } from "./session-detail";
import { SessionsPage as Page } from "./sessions-page";

/** Tooltips need the provider the shell mounts. */
function SessionsPage() {
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
});
afterAll(() => {
  server.close();
});

describe("SessionsPage", () => {
  it("lists sessions with the isolation callout for an admin", async () => {
    renderPage(SessionsPage, { path: "/i/$instance/sessions", url: "/i/prod-agentos/sessions" });
    const table = await screen.findByRole("table", { name: "Sessions" });
    expect(within(table).getByText("Refund for order 4471")).toBeInTheDocument();
    expect(within(table).getByText("paused")).toBeInTheDocument();
    expect(within(table).getByText("2,106")).toBeInTheDocument();
    expect(screen.getByText("2 of 2")).toBeInTheDocument();
    expect(await screen.findByText(/you're seeing all users as Owner/)).toBeInTheDocument();
  });

  it("opens a session: timeline, runs, summary, state and metrics", async () => {
    const user = userEvent.setup();
    renderPage(SessionsPage, {
      path: "/i/$instance/sessions/$sessionId",
      url: "/i/prod-agentos/sessions/ses_7f3a91c2",
    });
    const detail = await screen.findByRole("complementary", { name: "Session detail" });
    expect(await within(detail).findByText(/is waiting on approval/)).toBeInTheDocument();
    expect(within(detail).getByRole("link", { name: "Open in Approvals" })).toHaveAttribute(
      "href",
      "/i/prod-agentos/approvals?tool=refund_customer",
    );
    expect(within(detail).getByRole("button", { name: "Fork session" })).toBeInTheDocument();
    expect(within(detail).getByRole("button", { name: "Rename" })).toBeInTheDocument();

    await user.click(within(detail).getByRole("tab", { name: "Runs" }));
    expect(
      await within(detail).findByText(
        "Paused on refund_customer for approval. Continues when someone resolves it.",
      ),
    ).toBeInTheDocument();
    await user.click(within(detail).getByRole("tab", { name: "Summary" }));
    expect(await within(detail).findByText("Customer asked for a refund.")).toBeInTheDocument();
    await user.click(within(detail).getByRole("tab", { name: "State" }));
    expect(
      await within(detail).findByLabelText("session_state · editable with sessions:write"),
    ).toBeInTheDocument();
  });

  it("finds a session by pasting its id", async () => {
    const lookups: string[] = [];
    server.use(
      http.get(`${GATEWAY}/sessions/:session`, ({ params }) => {
        lookups.push(String(params.session));
        return HttpResponse.json({
          session_id: "0f8fad5b-d9cb-469f-a165-70867728950e",
          session_name: "Pasted",
          user_id: "u1",
          agent_id: "support-triage",
        });
      }),
    );
    const user = userEvent.setup();
    renderPage(SessionsPage, { path: "/i/$instance/sessions", url: "/i/prod-agentos/sessions" });
    await user.type(
      await screen.findByLabelText("Search name or session_id"),
      "0f8fad5b-d9cb-469f-a165-70867728950e",
    );
    expect(await screen.findByText("Pasted")).toBeInTheDocument();
    expect(lookups).toContain("0f8fad5b-d9cb-469f-a165-70867728950e");
  });
});

describe("runNote", () => {
  it("says what happened in plain words", () => {
    const base = {
      content: "",
      reasoning: "",
      tools: [],
      members: {},
      memberOrder: [],
      tasks: [],
      steps: [],
      openSteps: [],
      lastEventIndex: -1,
      eventCount: 0,
      unknownEvents: 0,
    };
    expect(
      runNote({
        ...base,
        status: "error",
        error: { message: "provider overloaded", type: "ModelProviderError" },
      }),
    ).toBe("Failed with ModelProviderError: provider overloaded");
    expect(runNote({ ...base, status: "completed" })).toBe("Completed without tool calls.");
  });
});
