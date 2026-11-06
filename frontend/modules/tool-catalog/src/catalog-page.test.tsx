// The tool catalog page: entries per level with their badges and "also offered as" hints, and per instance what the
// runtime pulled and how each entry is doing there.
import { renderPage, sampleOrgHandlers, toolCatalogHandlers } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ToolCatalogPage as Page } from "./catalog-page";

function ToolCatalogPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...toolCatalogHandlers(), ...sampleOrgHandlers()];
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

const PATH = "/access/tool-catalog";

describe("ToolCatalogPage", () => {
  it("lists organization entries with what else offers the same tool", async () => {
    renderPage(ToolCatalogPage, { path: PATH });
    const list = await screen.findByRole("list", { name: "org entries" });
    const cards = within(list).getAllByRole("listitem");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent("Linear");
    expect(cards[0]).toHaveTextContent("org-linear");
    expect(cards[0]).toHaveTextContent("MCP server · streamable-http");
    expect(cards[1]).toHaveTextContent("Also offered as Team · Data (Data search)");
  });

  it("shows team entries with their group", async () => {
    const user = userEvent.setup();
    renderPage(ToolCatalogPage, { path: PATH });
    await user.click(await screen.findByRole("tab", { name: "Teams" }));
    const list = await screen.findByRole("list", { name: "team entries" });
    expect(within(list).getAllByText("Team · Data")).toHaveLength(2);
    expect(list).toHaveTextContent("team-data-warehouse");
  });

  it("shows how each instance's runtime is doing with the catalog", async () => {
    const user = userEvent.setup();
    renderPage(ToolCatalogPage, { path: PATH });
    await user.click(await screen.findByRole("tab", { name: "Instances" }));
    const instances = await screen.findByRole("list", { name: "Instances" });
    expect(await within(instances).findAllByText("bridge 0.2.0")).not.toHaveLength(0);
    expect(within(instances).getAllByText("missing credential")).not.toHaveLength(0);
    expect(within(instances).getAllByText("Set WAREHOUSE_KEY on the runtime.")).not.toHaveLength(0);
  });
});
