import {
  API,
  p01Handlers,
  renderPage,
  studioHandlers,
  triageDetail,
  type StudioCalls,
} from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EditorView } from "@codemirror/view";
import { http, HttpResponse } from "msw";
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
  Object.defineProperty(Range.prototype, "getClientRects", {
    configurable: true,
    value: () => Object.assign([], { item: () => null }),
  });
  Object.defineProperty(Range.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => new DOMRect(),
  });
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

  it("reads edited code back into the form and saves the code with the draft", async () => {
    const parses: Record<string, unknown>[] = [];
    const edited = { ...triageDetail().draft?.config, description: "Hand-tuned in code" };
    server.use(
      http.post(`${API}/instances/:instance/studio/parse`, async ({ request }) => {
        parses.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({
          ok: true,
          config: edited,
          variable: "support_triage",
          diagnostics: [],
          spans: {},
          code_owned: ["pre_hooks"],
          ruff: { available: true, status: "ruff · 0 errors", formatted: false, messages: [] },
        });
      }),
    );
    renderPage(AgentEditorPage, EDITOR);
    const content = await screen.findByRole("textbox", { name: /^Generated agents\// }, { timeout: 5_000 });
    const view = EditorView.findFromDOM(content);
    if (!view) throw new Error("no editor");
    view.dispatch({ changes: { from: view.state.doc.length, insert: "# hand-tuned\n" } });

    expect(await screen.findByText("Code-backed · your code is kept as written")).toBeInTheDocument();
    expect(await screen.findByText("Synced with form · 1 code-owned")).toBeInTheDocument();
    expect(parses[0]).toMatchObject({ kind: "agent", component_id: "support-triage" });
    // The previous test's pending autosave may land first: wait for the save that carries the code.
    await waitFor(
      () => {
        expect(calls.saves.some((item) => typeof item.code === "string")).toBe(true);
      },
      { timeout: 5_000 },
    );
    const saved = calls.saves.find((item) => typeof item.code === "string") as {
      code: string;
      config: { description: string };
    };
    expect(saved.code.endsWith("# hand-tuned\n")).toBe(true);
    expect(saved.config.description).toBe("Hand-tuned in code");
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
