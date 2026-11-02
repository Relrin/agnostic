import { observeHandlers, p01Handlers, p02Handlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { TracesPage as Page } from "./traces-page";

/** Tooltips need the provider the shell mounts. */
function TracesPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...p01Handlers(), ...p02Handlers(), ...observeHandlers()];
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

const URL = "/i/prod-agentos/traces/tr_9c1e7d40";

describe("TracesPage", () => {
  it("lists traces and shows the selected one as a waterfall with span attributes", async () => {
    renderPage(TracesPage, { path: "/i/$instance/traces/$traceId", url: URL });
    const list = await screen.findByRole("table", { name: "Traces" });
    expect(await within(list).findByText("support-triage.run")).toBeInTheDocument();
    expect(within(list).getByText("1m 4s")).toHaveClass("text-warning"); // slower than 30 s

    expect(await screen.findByRole("heading", { name: /daily-brief\.run/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "session ses_6f12bd09" })).toHaveAttribute(
      "href",
      "/i/prod-agentos/sessions/ses_6f12bd09",
    );
    const waterfall = screen.getByRole("table", { name: "Span waterfall" });
    expect(within(waterfall).getAllByText("web_search")).toHaveLength(2);

    // The first failing tool call is selected: its OpenInference attributes are shown.
    const attributes = screen.getByRole("table", { name: "Span attributes" });
    expect(within(attributes).getByText("TimeoutError")).toBeInTheDocument();
    expect(within(attributes).getByText("TOOL")).toBeInTheDocument();
    expect(
      screen.getByText(/llm.model_name claude-haiku-5-5 · llm.token_count.prompt 10,516/),
    ).toBeInTheDocument();

    expect(await screen.findByText("research-team.run")).toBeInTheDocument();
    expect(screen.getByText("31,840 ms ×288")).toBeInTheDocument();
  });

  it("compares with the last successful run: ghost bars, the timing table and the diagnosis", async () => {
    const user = userEvent.setup();
    renderPage(TracesPage, { path: "/i/$instance/traces/$traceId", url: URL });
    const toggle = await screen.findByRole("button", { name: "Compare with last successful run" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);

    const table = await screen.findByRole("table", {
      name: "Span timings compared with the last successful run",
    });
    const search = within(table).getByText("web_search").closest("tr");
    expect(search).not.toBeNull();
    expect(within(search as HTMLElement).getByText("30.0 s ×2")).toHaveClass("text-danger");
    const write = within(table).getByText("Write brief").closest("tr");
    expect(within(write as HTMLElement).getByText("not run")).toBeInTheDocument();
    expect(screen.getByText(/so the workflow never reached `Write brief`/)).toBeInTheDocument();
    expect(document.querySelectorAll("[data-ghost]").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Compare with last successful run" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("switches to the tree view", async () => {
    const user = userEvent.setup();
    renderPage(TracesPage, { path: "/i/$instance/traces/$traceId", url: URL });
    await user.click(await screen.findByRole("radio", { name: "Tree" }));
    const tree = screen.getByRole("tree", { name: "Span tree" });
    expect(within(tree).getAllByRole("treeitem")).toHaveLength(7);
  });
});
