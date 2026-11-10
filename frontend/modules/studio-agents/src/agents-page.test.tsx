import {
  API,
  sampleOrgHandlers,
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
const handlers = () => [...sampleOrgHandlers(), ...studioHandlers(calls)];
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
    // Defined in code: it opens read-only.
    expect(within(table).getByRole("link", { name: "kb-researcher" })).toHaveAttribute(
      "href",
      "/i/staging-agentos/studio/agents/kb-researcher?source=code",
    );
    expect(within(table).getByLabelText("Read-only: defined in code")).toBeInTheDocument();
  });

  it("duplicates an agent defined in code into a new one stored in Studio", async () => {
    const user = userEvent.setup();
    const created: Record<string, unknown>[] = [];
    server.use(
      http.post(`${API}/instances/:instance/studio/components`, async ({ request }) => {
        created.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          { ...triageDetail(), component: { ...triageDetail().component, id: "kb-copy", name: "kb-copy" } },
          { status: 201 },
        );
      }),
    );
    renderPage(AgentsPage, { path: "/i/$instance/studio/agents", url: "/i/staging-agentos/studio/agents" });
    await user.click(await screen.findByRole("button", { name: "Duplicate kb-researcher" }));
    const dialog = await screen.findByRole("dialog", { name: "Duplicate kb-researcher" });
    const name = within(dialog).getByRole("textbox", { name: "Name of the copy" });
    expect(name).toHaveValue("kb-researcher-copy");
    await user.clear(name);
    await user.type(name, "kb-copy");
    await user.click(within(dialog).getByRole("button", { name: "Duplicate agent" }));
    await waitFor(() => {
      expect(created).toHaveLength(1);
    });
    expect(created[0]).toMatchObject({
      kind: "agent",
      name: "kb-copy",
      mode: "duplicate",
      source_id: "kb-researcher",
      source_origin: "code",
    });
  });
});

describe("renaming an agent", () => {
  it("renames from the list, keeping the id, and only for agents stored in Studio", async () => {
    const user = userEvent.setup();
    calls.patches = [];
    renderPage(AgentsPage, { path: "/i/$instance/studio/agents", url: "/i/staging-agentos/studio/agents" });
    await screen.findByRole("link", { name: "support-triage" });
    expect(screen.queryByRole("button", { name: "Rename kb-researcher" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Rename support-triage" }));
    const dialog = await screen.findByRole("dialog", { name: "Rename support-triage" });
    const name = within(dialog).getByRole("textbox", { name: "Name" });
    expect(name).toHaveValue("support-triage");
    const submit = within(dialog).getByRole("button", { name: "Rename" });
    expect(submit).toBeDisabled(); // nothing changed yet
    await user.clear(name);
    expect(submit).toBeDisabled();
    await user.type(name, "  Support triage ");
    await user.click(submit);

    await waitFor(() => {
      expect(calls.patches).toEqual([{ id: "support-triage", body: { name: "Support triage" } }]);
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("shows why a rename was refused and keeps the dialog open", async () => {
    const user = userEvent.setup();
    server.use(
      http.patch(`${API}/instances/:instance/studio/components/:id`, () =>
        HttpResponse.json(
          {
            type: "about:blank",
            code: "scope_missing",
            title: "Not allowed",
            status: 403,
            detail: "You need components:write on staging-agentos.",
          },
          { status: 403 },
        ),
      ),
    );
    renderPage(AgentsPage, { path: "/i/$instance/studio/agents", url: "/i/staging-agentos/studio/agents" });
    await user.click(await screen.findByRole("button", { name: "Rename support-triage" }));
    const dialog = await screen.findByRole("dialog", { name: "Rename support-triage" });
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "-2");
    await user.click(within(dialog).getByRole("button", { name: "Rename" }));
    expect(
      await within(dialog).findByText("You need components:write on staging-agentos."),
    ).toBeInTheDocument();
  });

  it("renames from the editor and saves the draft with the revision the rename returned", async () => {
    const user = userEvent.setup();
    calls.patches = [];
    renderPage(AgentEditorPage, EDITOR);
    await user.click(await screen.findByRole("button", { name: "Rename" }));
    const dialog = await screen.findByRole("dialog", { name: "Rename support-triage" });
    const name = within(dialog).getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Support triage");
    await user.click(within(dialog).getByRole("button", { name: "Rename" }));
    await waitFor(() => {
      expect(calls.patches).toEqual([{ id: "support-triage", body: { name: "Support triage" } }]);
    });
    // The draft the editor holds takes the name; its next save carries the revision the rename left.
    await waitFor(
      () => {
        expect(calls.saves.some((item) => item.revision === "r-renamed")).toBe(true);
      },
      { timeout: 5_000 },
    );
    const saved = calls.saves.find((item) => item.revision === "r-renamed") as { config: { name: string } };
    expect(saved.config.name).toBe("Support triage");
  });
});

describe("AgentEditorPage defined in code", () => {
  const CODE = {
    path: "/i/$instance/studio/agents/$componentId",
    url: "/i/staging-agentos/studio/agents/kb-researcher?source=code",
  };

  it("shows the config read-only, with where it is defined and no way to save or publish", async () => {
    renderPage(AgentEditorPage, CODE);
    expect(await screen.findByText("Locked: defined in code")).toBeInTheDocument();
    expect(screen.getByText("Defined in code · app.agents.kb_researcher:7 · read-only")).toBeInTheDocument();
    const instruction = await screen.findByRole("textbox", { name: "Instruction 1" });
    expect(instruction).toHaveValue("Search the knowledge base first.");
    expect(instruction).toHaveAttribute("readonly");
    for (const name of ["Save draft", "Versions", "Rename", /^Publish/, "Add instruction"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("duplicates it to edit", async () => {
    const user = userEvent.setup();
    renderPage(AgentEditorPage, CODE);
    const [first] = await screen.findAllByRole("button", { name: "Duplicate to edit" });
    if (!first) throw new Error("no Duplicate to edit button");
    await user.click(first);
    const dialog = await screen.findByRole("dialog", { name: "Duplicate kb-researcher" });
    expect(within(dialog).getByText(/The original stays defined in code, unchanged/)).toBeInTheDocument();
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
