import { sampleOrgHandlers, renderPage, studioHandlers } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { RegistryPage as Page } from "./registry-page";

function RegistryPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...sampleOrgHandlers(), ...studioHandlers()];
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

describe("RegistryPage", () => {
  it("lists tools with counts and explains a tool that needs approval", async () => {
    const user = userEvent.setup();
    renderPage(RegistryPage, {
      path: "/i/$instance/studio/registry/$type/$name",
      url: "/i/staging-agentos/studio/registry/tool/refund_customer",
    });
    const tabs = await screen.findByRole("tablist", { name: "Entry types" });
    expect(within(tabs).getByRole("tab", { name: /Tools/ })).toHaveAttribute("aria-selected", "true");
    const table = screen.getByRole("table", { name: "Registry entries" });
    expect(
      await within(table).findByText("app.tools.billing.refund_customer · @approval"),
    ).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(4); // header + three tools

    const aside = screen.getByRole("complementary", { name: "Entry details" });
    expect(await within(aside).findByText("Requires approval")).toBeInTheDocument();
    expect(within(aside).getByText("v3 · v4 draft")).toBeInTheDocument();
    expect(within(aside).getByText("Available in Studio.")).toBeInTheDocument();

    await user.click(within(table).getByRole("button", { name: "create_ticket" }));
    expect(await screen.findByText("Not available in Studio.")).toBeInTheDocument();
    expect(screen.getByText("Not used by any agent, team or workflow yet.")).toBeInTheDocument();
  });

  it("filters by name", async () => {
    const user = userEvent.setup();
    renderPage(RegistryPage, {
      path: "/i/$instance/studio/registry",
      url: "/i/staging-agentos/studio/registry",
    });
    const table = await screen.findByRole("table", { name: "Registry entries" });
    await within(table).findByText("kb_lookup");
    await user.type(screen.getByRole("textbox", { name: "Filter by name" }), "refund");
    expect(within(table).queryByText("kb_lookup")).not.toBeInTheDocument();
    expect(screen.getByText("1 of 7 entries")).toBeInTheDocument();
  });
});
