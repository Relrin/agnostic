import { p01Handlers, renderPage, studioHandlers, type StudioCalls } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { AgentEditorPage as Editor, AgentsPage as Index } from "./agents-page";

function AgentEditorPage() {
  return (
    <TooltipProvider>
      <Editor />
    </TooltipProvider>
  );
}

function AgentsPage() {
  return (
    <TooltipProvider>
      <Index />
    </TooltipProvider>
  );
}

let calls: StudioCalls = { saves: [], publishes: [], promotions: [] };
const handlers = () => [...p01Handlers(), ...studioHandlers(calls)];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  calls = { saves: [], publishes: [], promotions: [] };
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

const EDITOR = {
  path: "/i/$instance/studio/agents/$componentId",
  url: "/i/staging-agentos/studio/agents/support-triage",
};

describe("AgentsPage", () => {
  it("lists Studio agents and agents defined in code", async () => {
    renderPage(AgentsPage, { path: "/i/$instance/studio/agents", url: "/i/staging-agentos/studio/agents" });
    const table = await screen.findByRole("table", { name: "Agents" });
    expect(await within(table).findByRole("link", { name: "support-triage" })).toBeInTheDocument();
    expect(within(table).getByText("v4 draft")).toBeInTheDocument();
    expect(within(table).getByText("Defined in code")).toBeInTheDocument();
    expect(within(table).queryByRole("link", { name: "kb-researcher" })).not.toBeInTheDocument();
  });
});

describe("AgentEditorPage", () => {
  it("shows the draft against v3 and saves edits with the revision it loaded", async () => {
    const user = userEvent.setup();
    renderPage(AgentEditorPage, EDITOR);
    expect(await screen.findByText(/Draft v4 · based on v3/)).toBeInTheDocument();
    expect(await screen.findByText("Changed from mock-creative in v3")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /View diff against v3/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add instruction" }));
    await user.type(screen.getByRole("textbox", { name: "Instruction 3" }), "Never promise refunds.");
    expect(screen.getByText("new")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => {
      expect(calls.saves).toHaveLength(1);
    });
    const saved = calls.saves[0] as { revision: string; config: { instructions: string[] } };
    expect(saved.revision).toBe("r4");
    expect(saved.config.instructions).toEqual([
      "Classify by product area and urgency.",
      "Search the help center before answering.",
      "Never promise refunds.",
    ]);
  });

  it("publishes past a failed gate only with a reason", async () => {
    const user = userEvent.setup();
    renderPage(AgentEditorPage, EDITOR);
    await user.click(await screen.findByRole("button", { name: "Publish v4" }));
    const dialog = await screen.findByRole("dialog", { name: "Publish v4" });
    expect(
      await within(dialog).findByText("v4 draft (8.40) would be blocked from publishing."),
    ).toBeInTheDocument();
    const publish = within(dialog).getByRole("button", { name: "Override and publish v4" });
    expect(publish).toBeDisabled();
    await user.type(
      within(dialog).getByRole("textbox", { name: "Override reason" }),
      "Judge is wrong on two cases",
    );
    await user.click(publish);
    await waitFor(() => {
      expect(calls.publishes).toHaveLength(1);
    });
    expect(calls.publishes[0]).toMatchObject({ override_reason: "Judge is wrong on two cases" });
  });

  it("promotes after the registry check passes", async () => {
    const user = userEvent.setup();
    renderPage(AgentEditorPage, EDITOR);
    await user.click(await screen.findByRole("button", { name: "Promote…" }));
    const dialog = await screen.findByRole("dialog", { name: "Promote v3" });
    await user.click(within(dialog).getByRole("button", { name: "Check the target" }));
    expect(
      await within(dialog).findByText("Blocked: tool `refund_customer` isn't registered on the target."),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Check the target" }));
    expect(
      await within(dialog).findByText("All 3 registry references exist on the target."),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Publish on prod-agentos" })).toBeEnabled();
    expect(calls.promotions[0]).toMatchObject({ target: "prod-agentos", version: 3, include_children: true });
  });
});
