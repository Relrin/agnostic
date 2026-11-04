import {
  sampleOrgHandlers,
  renderPage,
  sourcesCalls,
  sourcesHandlers,
  type SourcesCalls,
} from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { SourcesPage as Page } from "./sources-page";

function SourcesPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

let calls: SourcesCalls = sourcesCalls();
const handlers = () => [...sourcesHandlers(calls), ...sampleOrgHandlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
beforeEach(() => {
  calls = sourcesCalls();
  server.resetHandlers(...handlers());
});
afterEach(() => {
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

const PATH = "/i/$instance/studio/sources";
const URL = "/i/staging-agentos/studio/sources";

describe("SourcesPage", () => {
  it("shows the sources with their chips, path mapping and sync policy", async () => {
    renderPage(SourcesPage, { path: PATH, url: URL });
    const list = await screen.findByRole("list", { name: "Connected sources" });
    const cards = within(list).getAllByRole("button");
    expect(cards).toHaveLength(3);
    expect(cards[0]).toHaveAttribute("aria-pressed", "true");
    expect(cards[0]).toHaveTextContent("northwind/agent-platform · main");
    expect(cards[0]).toHaveTextContent("↓ 2 incoming");
    expect(cards[0]).toHaveTextContent("↑ 1 outgoing");
    expect(cards[0]).toHaveTextContent("1 conflict");
    expect(cards[1]).toHaveTextContent("up to date");
    expect(cards[1]).toHaveTextContent("read-only");
    expect(cards[2]).toHaveTextContent("in sync · 18 files");

    const mappings = screen.getByRole("list", { name: "Path mappings" });
    expect(mappings).toHaveTextContent("agents/*.py");
    expect(mappings).toHaveTextContent("Agents · 6");
    expect(mappings).toHaveTextContent("Registry · read-only");
    expect(screen.getByRole("radio", { name: "On demand" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Open a pull request" })).toBeChecked();
  });

  it("lists incoming changes with what pulling does, and pulls them as drafts", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    const incoming = await screen.findByRole("region", { name: "Incoming" });
    expect(
      await within(incoming).findByText("Becomes draft v9 of ticket-router, next to your draft v8"),
    ).toBeInTheDocument();
    expect(within(incoming).getByText("Becomes draft v9 of kb-researcher")).toBeInTheDocument();
    await user.click(within(incoming).getByRole("checkbox", { name: "Include agents/kb_researcher.py" }));
    await waitFor(() => {
      expect(calls.includes).toEqual([{ change: "sch_2", included: false }]);
    });
    await user.click(within(incoming).getByRole("button", { name: "Pull 2 as drafts" }));
    await waitFor(() => {
      expect(calls.pulls).toEqual([["sch_1", "sch_2"]]);
    });
  });

  it("shows the outgoing change with the commit composer and commits it", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    const outgoing = await screen.findByRole("region", { name: "Outgoing" });
    expect(
      await within(outgoing).findByText(
        "Draft v4 by Priya Nair · temperature 0.7 → 0.2, one new instruction",
      ),
    ).toBeInTheDocument();
    expect(
      await within(outgoing).findByText(
        "Branch studio/support-triage-v4 · PR into main · 1 review from Platform required",
      ),
    ).toBeInTheDocument();
    expect(within(outgoing).getByRole("textbox", { name: "Commit message" })).toHaveValue(
      "support-triage: lower temperature, add refund rule",
    );
    await user.click(within(outgoing).getByRole("button", { name: "Commit & open PR" }));
    await waitFor(() => {
      expect(calls.commits).toEqual([
        { change_ids: ["sch_out"], message: "support-triage: lower temperature, add refund rule" },
      ]);
    });
  });

  it("shows a conflict with both sides and resolves it", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    const conflict = await screen.findByRole("article", { name: "Conflict on instructions[2]" });
    expect(conflict).toHaveTextContent("Repo · e81f0c4 · Sam Rivera");
    expect(conflict).toHaveTextContent("Refunds over $200 need a manager.");
    expect(conflict).toHaveTextContent("Studio · draft v6 · Maya Chen");
    expect(conflict).toHaveTextContent("Refunds over $150 need a manager.");
    await user.click(within(conflict).getByRole("button", { name: "Keep repo" }));
    await waitFor(() => {
      expect(calls.resolutions).toEqual([{ conflict: "scf_1", resolution: "keep_repo" }]);
    });
  });

  it("saves the sync policy", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    await user.click(await screen.findByRole("radio", { name: "On every push to main, as drafts" }));
    await waitFor(() => {
      expect(calls.updates[0]).toMatchObject({ policy: { pull_mode: "on_push_as_drafts" }, version: 3 });
    });
  });
});
