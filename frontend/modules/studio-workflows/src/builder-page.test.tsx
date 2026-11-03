// The workflow builder against MSW: the ticket router on the canvas with its validation sentence and stats, adding
// a step from a connector and from the palette, the router's CEL checked and tried in the inspector, the executor
// picker, delete with undo from the keyboard, the code view highlighting the selected step, and the Runs tab.
import {
  p01Handlers,
  renderPage,
  studioHandlers,
  workflowCalls,
  workflowHandlers,
  type StudioCalls,
  type WorkflowCalls,
} from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { WorkflowBuilderPage as Builder } from "./builder-page";

function WorkflowBuilderPage() {
  return (
    <TooltipProvider>
      <Builder />
    </TooltipProvider>
  );
}

let calls: StudioCalls = { saves: [], publishes: [], promotions: [] };
let flows: WorkflowCalls = workflowCalls();
const handlers = () => [...p01Handlers(), ...workflowHandlers(flows), ...studioHandlers(calls)];
const server = setupServer(...handlers());

beforeAll(() => {
  // jsdom has no layout: React Flow and CodeMirror measure with these. Canvas nodes are clicked with fireEvent: a
  // pointer press would start React Flow's node drag, which needs a real window on the event.
  const ignore = () => undefined;
  globalThis.ResizeObserver = class {
    observe = ignore;
    unobserve = ignore;
    disconnect = ignore;
  };
  Object.defineProperty(window, "DOMMatrixReadOnly", {
    configurable: true,
    value: class {
      m22 = 1;
      constructor(transform?: string) {
        const scale = /scale\(([\d.]+)\)/.exec(transform ?? "");
        if (scale?.[1]) this.m22 = Number(scale[1]);
      }
    },
  });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get: () => 800 });
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 1200 });
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
  flows = workflowCalls();
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

const BUILDER = {
  path: "/i/$instance/studio/workflows/$componentId",
  url: "/i/staging-agentos/studio/workflows/ticket-router",
};

async function canvas() {
  const found = await screen.findByRole("application", { name: "Workflow canvas" });
  await within(found).findByRole("button", { name: /^Step Classify ticket/ }, { timeout: 5_000 });
  return found;
}

describe("WorkflowBuilderPage", () => {
  it("draws the ticket router with its validation, stats and branches", async () => {
    renderPage(WorkflowBuilderPage, BUILDER);
    const board = await canvas();
    expect(
      within(board).getByRole("button", { name: /^Router Route by category, cel · input/ }),
    ).toBeInTheDocument();
    expect(within(board).getByRole("button", { name: /^Parallel Investigate/ })).toBeInTheDocument();
    expect(within(board).getByRole("button", { name: /^Loop Draft & review/ })).toBeInTheDocument();
    expect(within(board).getByText("avg 1.1 s")).toBeInTheDocument();
    expect(within(board).getByText("Start · input")).toBeInTheDocument();
    expect(await screen.findByText(/12 steps · valid/)).toBeInTheDocument();
    expect(screen.getByText(/^Draft v8/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish v8" })).toBeInTheDocument();
    const palette = screen.getByRole("complementary", { name: "Step palette" });
    expect(within(palette).getByRole("button", { name: "Add a Router" })).toBeInTheDocument();
    expect(
      within(palette).getByRole("button", { name: "Add a step running agent support-triage" }),
    ).toBeInTheDocument();
  });

  it("adds a step from the palette after the selected one, saves it, and undoes it", async () => {
    const user = userEvent.setup();
    renderPage(WorkflowBuilderPage, BUILDER);
    const board = await canvas();
    fireEvent.click(within(board).getByRole("button", { name: /^Step Classify ticket/ }));
    const palette = screen.getByRole("complementary", { name: "Step palette" });
    await user.click(within(palette).getByRole("button", { name: "Add a Step" }));
    expect(
      await within(board).findByRole("button", { name: /^Step Step, no executor yet/ }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/13 steps · 1 problem/)).toBeInTheDocument();
    await waitFor(
      () => {
        expect(calls.saves.length).toBeGreaterThan(0);
      },
      { timeout: 5_000 },
    );
    const saved = calls.saves.at(-1)?.config as { steps: { name: string }[] };
    expect(saved.steps.map((step) => step.name)).toEqual([
      "Classify ticket",
      "Step",
      "Route by category",
      "Needs a human?",
    ]);

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(within(board).queryByRole("button", { name: /^Step Step,/ })).not.toBeInTheDocument();
    });
  });

  it("edits the router's selector with a live check, tries it, and lists its choices", async () => {
    const user = userEvent.setup();
    renderPage(WorkflowBuilderPage, BUILDER);
    const board = await canvas();
    fireEvent.click(within(board).getByRole("button", { name: /^Router Route by category/ }));
    const inspector = screen.getByRole("complementary", { name: "Step properties" });
    expect(within(inspector).getByRole("heading", { name: "Route by category" })).toBeInTheDocument();
    expect(within(inspector).getByText("step 2 of 12")).toBeInTheDocument();
    expect(
      await within(inspector).findByText("Returns string · every result matches a choice"),
    ).toBeInTheDocument();
    expect(flows.checks.at(-1)).toMatchObject({
      context: "router",
      choices: ["Billing", "Investigate", "Draft & review"],
    });
    expect(within(inspector).getByRole("button", { name: "previous_step_outputs" })).toBeInTheDocument();
    const choices = within(inspector).getByRole("region", { name: "Choices" });
    expect(within(choices).getByText("Parallel · 2 steps")).toBeInTheDocument();

    const sandbox = within(inspector).getByRole("region", { name: "Try the expression" });
    await user.type(
      within(sandbox).getByRole("textbox", { name: "Sample input" }),
      "I was charged twice, need a refund",
    );
    await user.click(within(sandbox).getByRole("button", { name: "Evaluate" }));
    expect(await within(sandbox).findByText('→ "Billing"')).toBeInTheDocument();
    expect(within(sandbox).getByText("Evaluated by agno on the instance.")).toBeInTheDocument();
  });

  it("removes a step from the keyboard and brings it back with undo", async () => {
    const user = userEvent.setup();
    renderPage(WorkflowBuilderPage, BUILDER);
    const board = await canvas();
    fireEvent.click(within(board).getByRole("button", { name: /^Step Classify ticket/ }));
    board.focus();
    await user.keyboard("{ArrowDown}");
    expect(within(board).getByRole("button", { name: /^Router Route by category/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.keyboard("{ArrowUp}{Delete}");
    await waitFor(() => {
      expect(within(board).queryByRole("button", { name: /^Step Classify ticket/ })).not.toBeInTheDocument();
    });
    board.focus();
    await user.keyboard("{Control>}z{/Control}");
    expect(await within(board).findByRole("button", { name: /^Step Classify ticket/ })).toBeInTheDocument();
  });

  it("shows the step's runs and its executor", async () => {
    const user = userEvent.setup();
    renderPage(WorkflowBuilderPage, BUILDER);
    const board = await canvas();
    fireEvent.click(within(board).getByRole("button", { name: /^Step Classify ticket/ }));
    const inspector = screen.getByRole("complementary", { name: "Step properties" });
    expect(within(inspector).getByText("agent · support-triage")).toBeInTheDocument();
    await user.click(within(inspector).getByRole("tab", { name: "Runs" }));
    expect(await within(inspector).findByText("Category: BILLING")).toBeInTheDocument();
  });

  it("shows the code with the selected step highlighted, and keeps the selection in the URL", async () => {
    const user = userEvent.setup();
    const { router } = renderPage(WorkflowBuilderPage, BUILDER);
    const board = await canvas();
    fireEvent.click(within(board).getByRole("button", { name: /^Router Route by category/ }));
    await waitFor(() => {
      expect(router.state.location.search).toMatchObject({ node: "steps[1]" });
    });
    await user.click(screen.getByRole("radio", { name: "Code" }));
    const code = await screen.findByRole("textbox", { name: "Generated workflows/component.py" });
    await waitFor(() => {
      expect(code.querySelectorAll(".cm-focus-line").length).toBeGreaterThan(0);
    });
    expect(screen.getByRole("complementary", { name: "Step properties" })).toBeInTheDocument();
  });
});
